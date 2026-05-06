// Canvas — the single-pane M3 view.
//
// Composes the chat rail (left), the force-directed graph (right), and the
// toolbar/legend/settings overlays. Owns:
//
//   - The cluster fetch lifecycle (refetch on chat send so the graph reflects
//     the agent's working set).
//   - The canvas camera (pan/zoom state). The Graph component drives the
//     mutable cameraRef; we bump cameraVersion to trigger re-renders.
//   - The continuous physics RAF loop that steps the layout each frame.
//   - The citation choreography: when ChatRail reports a new citation, we
//     pulse the matching node, fit-camera to all-cited-so-far, animate the
//     edge between previous and current citation as a flowing dash.
//
// Replaces every previous tab (Search, Chat, Cluster, Self, Entities,
// EntityDetail, ItemDetail, Questions, Settings).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ClusterResponse, type LLMSettings } from "../api/client";
import { ChatHistorySidebar } from "../components/canvas/ChatHistorySidebar";
import { ChatRail, type CitedRef } from "../components/canvas/ChatRail";
import { FilesModal } from "../components/canvas/files/FilesModal";
import { Graph, type GraphLink } from "../components/canvas/Graph";
import { Legend } from "../components/canvas/Legend";
import { SettingsModal } from "../components/canvas/SettingsModal";
import { Toolbar } from "../components/canvas/Toolbar";
import type { Variant } from "../components/canvas/NodeMark";
import {
  deriveCategory,
  type Category,
  type LinkKind,
} from "../lib/canvasColors";
import {
  initLayout,
  type Layout,
  type LayoutLink,
  type LayoutNode,
} from "../lib/forceLayout";

type DisplayNode = {
  id: string;
  label: string;
  cat: Category;
  isEgo: boolean;
  excerpt: string | null;
  itemId: string | null;
};

const SUGGESTIONS = [
  "What did I capture about portfolio?",
  "Who comes up most in my notes?",
  "Summarize what I've been thinking about lately",
];

export default function Canvas() {
  const [variant, setVariant] = useState<Variant>(
    (localStorage.getItem("m3-variant") as Variant) || "cosmos",
  );
  const [cluster, setCluster] = useState<ClusterResponse | null>(null);
  const [clusterErr, setClusterErr] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [settings, setSettings] = useState<LLMSettings | null>(null);

  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());
  const [preHighlighted, setPreHighlighted] = useState<Set<string>>(new Set());
  const [pulseId, setPulseId] = useState<string | null>(null);
  const [flowEdges, setFlowEdges] = useState<Set<string>>(new Set());
  const [cited, setCited] = useState<CitedRef[]>([]);
  const [camVer, setCamVer] = useState(0);

  // Active chat session id. Lifted out of ChatRail so the (forthcoming) chat
  // history sidebar can switch the rail to a different conversation by
  // updating this state. Persisted to localStorage so chats survive relaunch;
  // ChatRail rehydrates whenever this changes (including null = clear turns).
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : localStorage.getItem("m3-session-id"),
  );

  // Persist whenever it changes, single source of truth.
  useEffect(() => {
    if (activeSessionId) localStorage.setItem("m3-session-id", activeSessionId);
    else localStorage.removeItem("m3-session-id");
  }, [activeSessionId]);

  // Sidebar collapse state.
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("m3-sidebar-collapsed") === "1";
  });
  useEffect(() => {
    localStorage.setItem("m3-sidebar-collapsed", sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  // Bumped after a chat round-trip so the sidebar refetches titles + timestamps
  // (the auto-title pass writes async on the server, so we delay slightly).
  const [chatsRefreshKey, setChatsRefreshKey] = useState(0);

  const cameraRef = useRef({ x: 0, y: 0, k: 1 });
  const containerRef = useRef<HTMLDivElement>(null);
  const animRef = useRef<number | null>(null);
  const [viewSize, setViewSize] = useState({ w: 1000, h: 700 });

  useEffect(() => { localStorage.setItem("m3-variant", variant); }, [variant]);

  // Initial whole-brain graph + settings load. The canvas is at-rest by
  // default; chat citations highlight subsets of this graph rather than
  // refetching a topic-scoped cluster on every send.
  useEffect(() => {
    api.clusterAll().then(setCluster).catch(e => setClusterErr(String(e)));
    api.settings().then(setSettings).catch(() => {/* not configured / no server yet */});
  }, []);

  // Refetch settings when modal closes — in case the user changed providers.
  useEffect(() => {
    if (!settingsOpen) {
      api.settings().then(setSettings).catch(() => {});
    }
  }, [settingsOpen]);

  // Derive display nodes/edges from the cluster response. Memoized so we don't
  // rebuild the layout every render — only when the cluster identity changes.
  const display = useMemo(() => {
    if (!cluster) {
      return { nodes: [] as DisplayNode[], links: [] as GraphLink[] };
    }
    const nodes: DisplayNode[] = cluster.nodes.map(n => ({
      id: n.id,
      label: n.label || n.id,
      cat: deriveCategory({ type: n.type as "query" | "item" | "entity", entity_type: n.entity_type, kind: n.kind }),
      isEgo: n.type === "query",
      excerpt: n.excerpt,
      itemId: n.item_id,
    }));
    const links: GraphLink[] = cluster.edges.map(e => ({
      s: e.source,
      t: e.target,
      kind: (["matched", "hooks", "related"] as const).includes(e.kind as LinkKind)
        ? (e.kind as LinkKind)
        : "related",
    }));
    return { nodes, links };
  }, [cluster]);

  const layout = useMemo<Layout>(() => {
    const nodes: LayoutNode[] = display.nodes.map(n => ({ id: n.id, cat: n.cat }));
    const links: LayoutLink[] = display.links.map(l => ({ s: l.s, t: l.t }));
    const ego = display.nodes.find(n => n.isEgo)?.id;
    return initLayout(nodes, links, { width: 1600, height: 1100, egoId: ego });
    // Re-init on cluster identity. Force layouts can't be incrementally
    // mutated with new node sets without state surgery; cleaner to rebuild.
  }, [display.nodes, display.links]);

  // Resize observer for the canvas container — used for camera fit.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) setViewSize({ w: e.contentRect.width, h: e.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Continuous physics — never stops, so nodes breathe + react to drag/hover.
  useEffect(() => {
    let raf = 0;
    let lastTick = 0;
    function loop(now: number) {
      layout.step();
      if (now - lastTick > 22) { setCamVer(v => (v + 1) & 0xffff); lastTick = now; }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [layout]);

  // Initial fit when layout + viewport are ready.
  useEffect(() => {
    if (viewSize.w < 10 || layout.state.length === 0) return;
    fitTo(layout.state.map(s => s.id));
    // We deliberately do NOT depend on `layout` here — only fit on first
    // viewSize-becomes-known per layout instance. Subsequent fits are caller-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewSize.w, layout]);

  const fitTo = useCallback(
    (ids: string[], pad = 140, duration = 500) => {
      const nodes = layout.state.filter(s => ids.includes(s.id));
      if (!nodes.length) return;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const s of nodes) {
        if (s.x < minX) minX = s.x;
        if (s.y < minY) minY = s.y;
        if (s.x > maxX) maxX = s.x;
        if (s.y > maxY) maxY = s.y;
      }
      minX -= pad; minY -= pad; maxX += pad; maxY += pad;
      const w = maxX - minX, h = maxY - minY;
      const k = Math.min(viewSize.w / w, viewSize.h / h, 1.8);
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      animateCamera(
        { x: viewSize.w / 2 - cx * k, y: viewSize.h / 2 - cy * k, k },
        duration,
      );
    },
    [layout, viewSize.w, viewSize.h],
  );

  function animateCamera(to: { x: number; y: number; k: number }, duration: number) {
    if (animRef.current) cancelAnimationFrame(animRef.current);
    const from = { ...cameraRef.current };
    const t0 = performance.now();
    function tick(now: number) {
      const t = Math.min(1, (now - t0) / duration);
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      cameraRef.current = {
        x: from.x + (to.x - from.x) * e,
        y: from.y + (to.y - from.y) * e,
        k: from.k + (to.k - from.k) * e,
      };
      setCamVer(v => v + 1);
      if (t < 1) animRef.current = requestAnimationFrame(tick);
    }
    animRef.current = requestAnimationFrame(tick);
  }

  function bumpCam() { setCamVer(v => v + 1); }

  function setZoom(newK: number) {
    const k = Math.max(0.25, Math.min(3.5, newK));
    const cam = cameraRef.current;
    const cx = viewSize.w / 2, cy = viewSize.h / 2;
    const wx = (cx - cam.x) / cam.k;
    const wy = (cy - cam.y) / cam.k;
    cameraRef.current = { k, x: cx - wx * k, y: cy - wy * k };
    bumpCam();
  }

  function focusNode(id: string) {
    const s = layout.byId.get(id);
    if (!s) return;
    const k = Math.max(1.5, cameraRef.current.k);
    animateCamera(
      { x: viewSize.w / 2 - s.x * k, y: viewSize.h / 2 - s.y * k, k },
      450,
    );
    setPulseId(id);
    window.setTimeout(() => setPulseId(p => (p === id ? null : p)), 1400);
  }

  // Pre-highlight: substring-match cluster node labels against the typed text.
  // Cheap, runs on every keystroke; nodes get a dashed ring on the canvas.
  const onTyping = useCallback(
    (text: string) => {
      const trimmed = text.trim().toLowerCase();
      if (!trimmed) { setPreHighlighted(new Set()); return; }
      const tokens = trimmed.split(/\s+/).filter(t => t.length > 3);
      if (tokens.length === 0) { setPreHighlighted(new Set()); return; }
      const hits = new Set<string>();
      for (const n of display.nodes) {
        const hay = (n.label + " " + (n.excerpt ?? "") + " " + n.cat).toLowerCase();
        if (tokens.some(t => hay.includes(t))) hits.add(n.id);
      }
      setPreHighlighted(hits);
    },
    [display.nodes],
  );

  // Item-id -> CitedRef resolver. Citations come back from the agent as raw
  // item_ids; the cluster gives us nodes keyed `item:<uuid>`.
  const resolveCitation = useCallback(
    (itemId: string): CitedRef | null => {
      const node = display.nodes.find(n => n.itemId === itemId);
      if (!node) return null;
      return { id: node.id, itemId, label: node.label, cat: node.cat };
    },
    [display.nodes],
  );

  // Track the previous citation outside React state so we can read it
  // synchronously inside handleCitation. Reading it from `cited` via a state
  // updater would race with the very setCited call that adds the new ref.
  const lastCitedRef = useRef<CitedRef | null>(null);

  const handleCitation = useCallback(
    (ref: CitedRef) => {
      const prev = lastCitedRef.current;
      lastCitedRef.current = ref;

      setCited(curr => (curr.some(c => c.id === ref.id) ? curr : [...curr, ref]));
      setHighlighted(curr => {
        const next = new Set(curr);
        next.add(ref.id);
        return next;
      });
      setPulseId(ref.id);
      window.setTimeout(() => setPulseId(p => (p === ref.id ? null : p)), 1400);

      if (prev && prev.id !== ref.id) {
        const key = findEdgeKey(prev.id, ref.id);
        if (key) {
          setFlowEdges(s => { const n = new Set(s); n.add(key); return n; });
          window.setTimeout(
            () => setFlowEdges(s => { const n = new Set(s); n.delete(key); return n; }),
            1800,
          );
        }
      }

      setTimeout(() => {
        setHighlighted(curr => {
          fitTo(Array.from(curr), 200, 600);
          return curr;
        });
      }, 0);
    },
    [fitTo, display.links],
  );

  function findEdgeKey(a: string, b: string): string | null {
    const direct = display.links.find(l => l.s === a && l.t === b);
    if (direct) return `${a}→${b}`;
    const reverse = display.links.find(l => l.s === b && l.t === a);
    if (reverse) return `${b}→${a}`;
    return null;
  }

  const onReset = useCallback(() => {
    setHighlighted(new Set());
    setCited([]);
    setFlowEdges(new Set());
    setPulseId(null);
    setPreHighlighted(new Set());
    lastCitedRef.current = null;
    fitTo(layout.state.map(s => s.id));
  }, [fitTo, layout]);

  // Each new chat round resets the citation choreography state but keeps the
  // graph itself stable — citations from the agent's reply highlight nodes in
  // the existing whole-brain graph instead of swapping in a topic-scoped one.
  // The `text` is unused for now; kept on the signature for future use (e.g.
  // pre-fetching items the agent is likely to cite).
  const onSend = useCallback((_text: string) => {
    setHighlighted(new Set());
    setCited([]);
    setFlowEdges(new Set());
    setPulseId(null);
    lastCitedRef.current = null;
    // After the round-trip the agent will have minted/updated a session and
    // the auto-title task fires async server-side. Wait briefly so the title
    // and updated_at land before the sidebar refetches.
    window.setTimeout(() => setChatsRefreshKey(k => k + 1), 1500);
  }, []);

  const presentLinkKinds: LinkKind[] = useMemo(() => {
    const set = new Set<LinkKind>();
    for (const l of display.links) set.add(l.kind);
    return Array.from(set);
  }, [display.links]);

  return (
    <div className="m3-app" data-variant={variant}>
      <ChatHistorySidebar
        activeSessionId={activeSessionId}
        onSelectSession={(sid) => setActiveSessionId(sid)}
        onNewChat={() => setActiveSessionId(null)}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(c => !c)}
        refreshKey={chatsRefreshKey}
      />
      <ChatRail
        onTyping={onTyping}
        onSend={onSend}
        onCitation={handleCitation}
        resolveCitation={resolveCitation}
        cited={cited}
        onCitedClick={focusNode}
        onReset={onReset}
        suggestions={SUGGESTIONS}
        sessionId={activeSessionId}
        onSessionChange={setActiveSessionId}
      />
      <main className="m3-canvas-area" ref={containerRef}>
        {clusterErr && (
          <div className="m3-canvas-error">
            Couldn't load cluster: {clusterErr}
          </div>
        )}
        <Graph
          layout={layout}
          nodes={display.nodes}
          links={display.links}
          variant={variant}
          showHulls={true}
          highlighted={highlighted}
          preHighlighted={preHighlighted}
          pulseId={pulseId}
          flowEdges={flowEdges}
          cameraRef={cameraRef}
          onCamera={bumpCam}
          onNodeClick={focusNode}
          cameraVersion={camVer}
        />
        <Toolbar
          variant={variant}
          setVariant={setVariant}
          onFit={() => fitTo(layout.state.map(s => s.id))}
          zoom={cameraRef.current.k}
          setZoom={setZoom}
          onSettings={() => setSettingsOpen(true)}
          onFiles={() => setFilesOpen(true)}
          unconfigured={settings != null && !settings.configured}
        />
        <div className="m3-bottom-right">
          <Legend kinds={presentLinkKinds} />
        </div>
      </main>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <FilesModal
        open={filesOpen}
        onClose={() => setFilesOpen(false)}
        onIngest={resp => {
          // Pulse each touched entity node so the user sees their upload
          // strengthening the graph in real time. We refetch the cluster
          // afterwards so newly-created entities show up too.
          const touched = (resp.entities_touched || []).map(slugify);
          for (const slug of touched) {
            const id = `entity:${slug}`;
            if (layout.byId.has(id)) {
              setPulseId(id);
              window.setTimeout(() => setPulseId(p => (p === id ? null : p)), 1400);
            }
          }
          api.clusterAll().then(setCluster).catch(() => {});
        }}
        onFocusEntity={slug => focusNode(`entity:${slug}`)}
      />
    </div>
  );
}

function slugify(name: string): string {
  return (name || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    || "unknown";
}
