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
import { api, type ClusterNode, type ClusterResponse, type LLMSettings } from "../api/client";
import { ChatHistorySidebar } from "../components/canvas/ChatHistorySidebar";
import { ChatRail, type CitedRef } from "../components/canvas/ChatRail";
import { DetailPanel } from "../components/canvas/DetailPanel";
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
  sources?: number;
  /** When this node was first captured / created. Used by v2 force layout
   *  to place it on the appropriate recency ring. */
  whenIso?: string | null;
  /** 768-dim topical signature embedding (or null if not indexed yet).
   *  Used by v2 force layout for topical attraction. */
  topicalVec?: number[] | null;
  /** Full proposition for claim nodes — rendered in the expanded card body. */
  proposition?: string | null;
  /** Numeric confidence — rendered in the expanded card metadata. */
  confidence?: number | null;
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

  // Bumped on every "new chat" click so ChatRail can always respond visibly,
  // even when activeSessionId was already null and React would otherwise
  // short-circuit setActiveSessionId(null).
  const [newChatNonce, setNewChatNonce] = useState(0);
  const startNewChat = useCallback(() => {
    setActiveSessionId(null);
    setNewChatNonce(n => n + 1);
  }, []);

  // Layered visibility. The default canvas is You + entities + their
  // syntheses — clean and readable. Claims and items are hidden by default;
  // they're either revealed globally via the toolbar toggles, or per-entity
  // by clicking an entity to expand it.
  const [showAllSources, setShowAllSources] = useState(false);
  const [showAllClaims, setShowAllClaims] = useState(false);
  const [expandedEntities, setExpandedEntities] = useState<Set<string>>(new Set());

  // Focus mode: clicking a node opens the detail panel and dims everything
  // that isn't the focused node or one of its 1-hop neighbors. Click the
  // canvas background or hit Esc to clear.
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);

  // Currently expanded claim node (canvas v2). Lives here so only one card
  // can be open at a time; ESC and canvas-click both clear it.
  const [expandedClaimId, setExpandedClaimId] = useState<string | null>(null);

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

  // Canvas v2 feature flag. localStorage dev override takes precedence so a
  // developer can flip v2 on without round-tripping through the settings API.
  const v2 = useMemo<boolean>(() => {
    if (typeof window !== "undefined" && window.localStorage.getItem("m3_canvas_v2") === "1") {
      return true;
    }
    return !!settings?.canvas_v2_enabled;
  }, [settings]);

  // Derive display nodes/edges from the cluster response. Memoized so we don't
  // rebuild the layout every render — only when the cluster identity or the
  // sources-visibility state changes.
  //
  // Items (raw uploaded files) are demoted: they're rendered only when the
  // user opts into the global "Sources" toggle, or when they hook into an
  // entity the user has explicitly expanded by clicking. Each entity carries
  // a `sources` count so the renderer can show a badge.
  const display = useMemo(() => {
    if (!cluster) {
      return { nodes: [] as DisplayNode[], links: [] as GraphLink[] };
    }

    // Map item->entity and claim->entity hooks so we can:
    //   (a) count sources/claims per entity for badges
    //   (b) reveal a node only when its entity has been expanded
    const sourcesByEntity = new Map<string, number>();
    const claimsByEntity = new Map<string, number>();
    const itemsByEntity = new Map<string, Set<string>>();
    const claimsByEntityIds = new Map<string, Set<string>>();
    for (const e of cluster.edges) {
      if (e.kind !== "hooks") continue;
      if (e.source.startsWith("item:") && e.target.startsWith("entity:")) {
        sourcesByEntity.set(e.target, (sourcesByEntity.get(e.target) ?? 0) + 1);
        let bucket = itemsByEntity.get(e.target);
        if (!bucket) { bucket = new Set(); itemsByEntity.set(e.target, bucket); }
        bucket.add(e.source);
      } else if (e.source.startsWith("claim:") && e.target.startsWith("entity:")) {
        claimsByEntity.set(e.target, (claimsByEntity.get(e.target) ?? 0) + 1);
        let bucket = claimsByEntityIds.get(e.target);
        if (!bucket) { bucket = new Set(); claimsByEntityIds.set(e.target, bucket); }
        bucket.add(e.source);
      }
    }

    const visibleItemIds = new Set<string>();
    const visibleClaimIds = new Set<string>();
    if (showAllSources) {
      for (const n of cluster.nodes) if (n.type === "item") visibleItemIds.add(n.id);
    } else {
      for (const entityId of expandedEntities) {
        const items = itemsByEntity.get(entityId);
        if (items) for (const id of items) visibleItemIds.add(id);
      }
    }
    if (showAllClaims) {
      for (const n of cluster.nodes) if (n.type === "claim") visibleClaimIds.add(n.id);
    } else {
      for (const entityId of expandedEntities) {
        const cls = claimsByEntityIds.get(entityId);
        if (cls) for (const id of cls) visibleClaimIds.add(id);
      }
    }

    const nodes: DisplayNode[] = [];
    for (const n of cluster.nodes) {
      if (n.type === "item" && !visibleItemIds.has(n.id)) continue;
      if (n.type === "claim" && !visibleClaimIds.has(n.id)) continue;
      nodes.push({
        id: n.id,
        label: n.label || n.id,
        cat: deriveCategory({ type: n.type as "query" | "item" | "entity" | "claim" | "synthesis", entity_type: n.entity_type, kind: n.kind }),
        isEgo: n.type === "query",
        excerpt: n.excerpt,
        itemId: n.item_id,
        sources: n.type === "entity" ? sourcesByEntity.get(n.id) : undefined,
        whenIso: n.when_iso ?? null,
        topicalVec: n.topical_vec ?? null,
        proposition: n.proposition ?? null,
        confidence: n.confidence ?? null,
      });
    }

    const visibleIds = new Set(nodes.map(n => n.id));
    const links: GraphLink[] = [];
    for (const e of cluster.edges) {
      if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) continue;
      links.push({
        s: e.source,
        t: e.target,
        kind: (["matched", "hooks", "related", "evidence", "synthesizes"] as const).includes(e.kind as LinkKind)
          ? (e.kind as LinkKind)
          : "related",
      });
    }

    return { nodes, links };
  }, [cluster, showAllSources, showAllClaims, expandedEntities]);

  const layout = useMemo<Layout>(() => {
    const nodes: LayoutNode[] = display.nodes.map(n => ({
      id: n.id, cat: n.cat,
      whenIso: n.whenIso ?? null,
      topicalVec: n.topicalVec ?? null,
    }));
    const links: LayoutLink[] = display.links.map(l => ({ s: l.s, t: l.t }));
    const ego = display.nodes.find(n => n.isEgo)?.id;
    return initLayout(nodes, links, { width: 1600, height: 1100, egoId: ego, v2 });
    // Re-init on cluster identity. Force layouts can't be incrementally
    // mutated with new node sets without state surgery; cleaner to rebuild.
  }, [display.nodes, display.links, v2]);

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

  // Initial fit when layout + viewport are ready. Centred on the ego (You),
  // not on the bounding-box midpoint — otherwise an asymmetric set of nodes
  // pulls the focal point off-centre and the user's "I am the centre" gets
  // visually relocated to a corner.
  useEffect(() => {
    if (viewSize.w < 10 || layout.state.length === 0) return;
    const ego = layout.state.find(s => s.pinned);
    let extentR = 0;
    if (ego) {
      for (const s of layout.state) {
        const d = Math.hypot(s.x - ego.x, s.y - ego.y);
        if (d > extentR) extentR = d;
      }
    }
    const pad = 140;
    if (ego && extentR > 0) {
      const span = (extentR + pad) * 2;
      const k = Math.min(viewSize.w / span, viewSize.h / span, 1.4);
      animateCamera(
        { x: viewSize.w / 2 - ego.x * k, y: viewSize.h / 2 - ego.y * k, k },
        500,
      );
    } else {
      fitTo(layout.state.map(s => s.id));
    }
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

  // Click handler that doubles as source-expansion for entity nodes: clicking
  // an entity toggles whether its source items are revealed in the graph.
  // Every click also opens the detail panel and dims non-neighbors so the
  // user can actually follow connections from the focused node.
  const onCanvasNodeClick = useCallback((id: string) => {
    if (id.startsWith("entity:")) {
      setExpandedEntities(curr => {
        const next = new Set(curr);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    }
    setFocusedNodeId(id);
    // Compute the 1-hop neighborhood and write it into `highlighted`. The
    // existing render path uses `dim = !highlighted.has(id)` to fade the rest.
    const ring = new Set<string>([id]);
    for (const e of display.links) {
      if (e.s === id) ring.add(e.t);
      else if (e.t === id) ring.add(e.s);
    }
    setHighlighted(ring);
    focusNode(id);
    // focusNode is stable enough — depending on layout/viewSize would re-bind on every frame
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, viewSize.w, viewSize.h, display.links]);

  const clearFocus = useCallback(() => {
    setFocusedNodeId(null);
    setHighlighted(new Set());
    setExpandedEntities(new Set());
    // Recenter the camera on You. The focus animation moves the camera off
    // ego when the user explores; clearing focus should put them back.
    const ego = layout.state.find(s => s.pinned);
    if (ego && viewSize.w >= 10) {
      let extentR = 0;
      for (const s of layout.state) {
        const d = Math.hypot(s.x - ego.x, s.y - ego.y);
        if (d > extentR) extentR = d;
      }
      const span = (extentR + 140) * 2;
      const k = Math.min(viewSize.w / span, viewSize.h / span, 1.4);
      animateCamera(
        { x: viewSize.w / 2 - ego.x * k, y: viewSize.h / 2 - ego.y * k, k },
        500,
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, viewSize.w, viewSize.h]);

  // Esc clears focus. Cheap key listener; lives on window so it works no
  // matter where the user clicked last.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        clearFocus();
        setExpandedClaimId(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearFocus]);

  const focusedNode = useMemo(() => {
    if (!focusedNodeId || !cluster) return null;
    return cluster.nodes.find(n => n.id === focusedNodeId) ?? null;
  }, [focusedNodeId, cluster]);

  const focusedNeighbors = useMemo(() => {
    if (!focusedNodeId || !cluster) return [];
    const out: { node: ClusterNode; relation: string }[] = [];
    const seen = new Set<string>();
    const byId = new Map(cluster.nodes.map(n => [n.id, n]));
    for (const e of cluster.edges) {
      let otherId: string | null = null;
      let relation = e.kind;
      if (e.source === focusedNodeId) otherId = e.target;
      else if (e.target === focusedNodeId) otherId = e.source;
      if (!otherId || seen.has(otherId)) continue;
      const n = byId.get(otherId);
      if (!n) continue;
      seen.add(otherId);
      out.push({ node: n, relation });
    }
    return out;
  }, [focusedNodeId, cluster]);

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
        onNewChat={startNewChat}
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
        newChatNonce={newChatNonce}
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
          onNodeClick={onCanvasNodeClick}
          onCanvasClick={() => {
            clearFocus();
            setExpandedClaimId(null);
          }}
          cameraVersion={camVer}
          v2={v2}
          expandedClaimId={expandedClaimId}
          onClaimToggle={(id: string) =>
            setExpandedClaimId(prev => (prev === id ? null : id))
          }
        />
        <DetailPanel
          node={focusedNode}
          neighbors={focusedNeighbors}
          onClose={clearFocus}
          onJumpTo={onCanvasNodeClick}
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
          showAllSources={showAllSources}
          onToggleSources={() => {
            setShowAllSources(v => !v);
            // Toggling the global flag clears per-entity expansions so the
            // graph stays predictable: either everything is shown or nothing
            // is shown (until the user clicks an entity).
            setExpandedEntities(new Set());
          }}
          showAllClaims={showAllClaims}
          onToggleClaims={() => {
            setShowAllClaims(v => !v);
            setExpandedEntities(new Set());
          }}
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
