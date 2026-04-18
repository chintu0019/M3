import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../components/canvas/canvas.css";
import "../components/canvas/graphCanvas.css";
import ChatDock from "../components/chat/ChatDock";
import NodeEditor from "../components/canvas/NodeEditor";
import LinkTypeMenu from "../components/canvas/LinkTypeMenu";
import NewNodeMenu from "../components/canvas/NewNodeMenu";
import CommandPalette, { PaletteAction } from "../components/palette/CommandPalette";
import ToolDrawer, { DrawerPane } from "../components/drawer/ToolDrawer";
import GraphCanvas, {
  CanvasVariant,
  CameraRef,
  GraphLink,
  GraphNode,
} from "../components/canvas/GraphCanvas";
import GraphToolbar from "../components/canvas/GraphToolbar";
import { GraphMinimap, GraphLegend } from "../components/canvas/GraphMinimap";
import { entityColor } from "../components/canvas/graphStyle";
import { initSim, PhysicsSim } from "../components/canvas/graphPhysics";
import { useHotkeys } from "../hooks/useHotkeys";
import { useTheme } from "../hooks/useTheme";
import {
  api,
  CanvasEdge,
  CanvasLayoutUpdate,
  CanvasNode,
  ChatCite,
} from "../api/client";

interface PendingLink {
  source: string;
  target: string;
  screenX: number;
  screenY: number;
}

interface PendingNewNode {
  flowX: number;
  flowY: number;
  screenX: number;
  screenY: number;
}

interface CitedEntry {
  id: string;
  name: string;
  cat: string;
}

const EMPTY_SET: Set<string> = new Set();

function catOf(n: CanvasNode): string {
  if (n.node_type === "entity") return n.data.entity_type || "entity";
  if (n.node_type === "insight") return n.data.insight_type || "insight";
  return "thread";
}

export default function Canvas() {
  const { setTheme } = useTheme();

  const [rawNodes, setRawNodes] = useState<CanvasNode[]>([]);
  const [rawEdges, setRawEdges] = useState<CanvasEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.canvas.get();
      setRawNodes(res.nodes);
      setRawEdges(res.edges);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Debounced layout flush.
  const pendingRef = useRef<Map<string, CanvasLayoutUpdate>>(new Map());
  const timerRef = useRef<number | null>(null);

  const flushLayout = useCallback(async () => {
    timerRef.current = null;
    const updates = Array.from(pendingRef.current.values());
    pendingRef.current.clear();
    if (!updates.length) return;
    try {
      await api.canvas.patchLayout(updates);
    } catch (err) {
      console.error("canvas layout flush failed", err);
    }
  }, []);

  const queueLayout = useCallback(
    (id: string, x: number, y: number) => {
      const idx = id.indexOf(":");
      const node_type = id.slice(0, idx);
      const node_id = id.slice(idx + 1);
      pendingRef.current.set(id, { node_type, node_id, x, y });
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => void flushLayout(), 400);
    },
    [flushLayout],
  );

  // Graph model derived from the canvas endpoint.
  const graphNodes = useMemo<GraphNode[]>(
    () =>
      rawNodes.map((n) => ({
        id: n.id,
        name: n.label,
        cat: catOf(n),
        overview: n.data.overview ?? n.data.description ?? null,
        facts: n.data.facts_since_render ?? 0,
      })),
    [rawNodes],
  );

  const graphLinks = useMemo<GraphLink[]>(
    () =>
      rawEdges.map((e) => ({
        s: e.source,
        t: e.target,
        type: e.edge_type,
      })),
    [rawEdges],
  );

  // Look for a "self" entity so we can pin it as the ego node if present.
  const egoId = useMemo(() => {
    const self = rawNodes.find((n) => n.node_type === "entity" && n.data.entity_type === "self");
    return self ? self.id : null;
  }, [rawNodes]);

  // Cache of live sim positions keyed by node id. Survives across sim rebuilds
  // (e.g. when the user creates a node or ends a thread) so existing nodes
  // don't snap back to their last-fetched coordinates.
  const posCacheRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  // Rebuild the sim only when the graph structure actually changes —
  // node ids or link endpoints. Label-only edits skip the rebuild.
  const graphKey = useMemo(
    () =>
      graphNodes
        .map((n) => n.id)
        .sort()
        .join("|") +
      "::" +
      graphLinks
        .map((l) => `${l.s}>${l.t}`)
        .sort()
        .join("|"),
    [graphNodes, graphLinks],
  );

  const sim = useMemo<PhysicsSim | null>(() => {
    if (!graphNodes.length) return null;
    const s = initSim(
      graphNodes.map((n) => ({ id: n.id, cat: n.cat, pinned: false })),
      graphLinks.map((l) => ({ s: l.s, t: l.t })),
      { width: 1600, height: 1100, egoId },
    );
    // Seed from cache first (preserves user-dragged positions across rebuilds),
    // falling back to the server-persisted coordinate for brand-new nodes.
    graphNodes.forEach((n) => {
      const st = s.byId.get(n.id);
      if (!st) return;
      const cached = posCacheRef.current.get(n.id);
      if (cached) {
        st.x = cached.x;
        st.y = cached.y;
        st.vx = 0;
        st.vy = 0;
        return;
      }
      const raw = rawNodes.find((r) => r.id === n.id);
      if (raw && raw.x != null && raw.y != null) {
        st.x = raw.x;
        st.y = raw.y;
        st.vx = 0;
        st.vy = 0;
      }
    });
    return s;
    // rawNodes is intentionally excluded — label-only edits shouldn't rebuild the sim.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey, egoId]);

  const [variant, setVariantState] = useState<CanvasVariant>(
    () => (localStorage.getItem("m3-canvas-variant") as CanvasVariant) || "cosmos",
  );
  const setVariant = useCallback((v: CanvasVariant) => {
    localStorage.setItem("m3-canvas-variant", v);
    setVariantState(v);
  }, []);

  const cameraRef = useRef<CameraRef>({ x: 0, y: 0, k: 1 });
  const [camVer, setCamVer] = useState(0);
  const bumpCam = useCallback(() => setCamVer((v) => v + 1), []);

  const viewRef = useRef<HTMLDivElement>(null);
  const [viewSize, setViewSize] = useState({ w: 1000, h: 700 });

  useEffect(() => {
    if (!viewRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setViewSize({ w: e.contentRect.width, h: e.contentRect.height });
    });
    ro.observe(viewRef.current);
    return () => ro.disconnect();
  }, []);

  // Physics loop. Bumps a tick counter ~45 Hz so the SVG re-renders.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!sim) return;
    let raf = 0;
    let last = 0;
    function loop(now: number) {
      sim!.step();
      if (now - last > 22) {
        setTick((t) => (t + 1) & 0xffff);
        last = now;
      }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [sim]);
  void tick;

  const onNodeDragEnd = useCallback(
    (id: string, x: number, y: number) => {
      posCacheRef.current.set(id, { x, y });
      queueLayout(id, x, y);
    },
    [queueLayout],
  );

  // Snapshot live positions into the cache right before any structural change
  // (new node, new edge, reload) so the about-to-be-rebuilt sim has fresh seeds.
  useEffect(() => {
    if (!sim) return;
    const snapshot = () => {
      sim.state.forEach((s) => {
        posCacheRef.current.set(s.id, { x: s.x, y: s.y });
      });
    };
    const interval = window.setInterval(snapshot, 1000);
    return () => {
      snapshot();
      window.clearInterval(interval);
    };
  }, [sim]);

  // Flush pending layout writes when the canvas unmounts.
  useEffect(() => {
    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
        void flushLayout();
      }
    };
  }, [flushLayout]);

  function animateCamera(to: CameraRef, duration: number) {
    const from = { ...cameraRef.current };
    const t0 = performance.now();
    let raf = 0;
    function tickAnim(now: number) {
      const t = Math.min(1, (now - t0) / duration);
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      cameraRef.current = {
        x: from.x + (to.x - from.x) * e,
        y: from.y + (to.y - from.y) * e,
        k: from.k + (to.k - from.k) * e,
      };
      bumpCam();
      if (t < 1) raf = requestAnimationFrame(tickAnim);
    }
    raf = requestAnimationFrame(tickAnim);
    return () => cancelAnimationFrame(raf);
  }

  const fitTo = useCallback(
    (ids: string[], pad = 140, duration = 500) => {
      if (!sim) return;
      const targetIds = ids.length ? ids : sim.state.map((s) => s.id);
      const nodes = sim.state.filter((s) => targetIds.includes(s.id));
      if (!nodes.length) return;
      let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
      nodes.forEach((s) => {
        if (s.x < minX) minX = s.x;
        if (s.y < minY) minY = s.y;
        if (s.x > maxX) maxX = s.x;
        if (s.y > maxY) maxY = s.y;
      });
      minX -= pad;
      minY -= pad;
      maxX += pad;
      maxY += pad;
      const w = maxX - minX,
        h = maxY - minY;
      if (w <= 0 || h <= 0) return;
      const k = Math.min(viewSize.w / w, viewSize.h / h, 1.8);
      const cx = (minX + maxX) / 2,
        cy = (minY + maxY) / 2;
      const targetX = viewSize.w / 2 - cx * k;
      const targetY = viewSize.h / 2 - cy * k;
      animateCamera({ x: targetX, y: targetY, k }, duration);
    },
    [sim, viewSize.w, viewSize.h],
  );

  // Fit on first load once sim + size are known.
  const didInitialFitRef = useRef(false);
  useEffect(() => {
    if (didInitialFitRef.current) return;
    if (!sim || viewSize.w < 50) return;
    didInitialFitRef.current = true;
    fitTo(sim.state.map((s) => s.id));
  }, [sim, viewSize.w, fitTo]);

  function setZoom(newK: number) {
    const k = Math.max(0.2, Math.min(3.5, newK));
    const cam = cameraRef.current;
    const cx = viewSize.w / 2,
      cy = viewSize.h / 2;
    const worldX = (cx - cam.x) / cam.k;
    const worldY = (cy - cam.y) / cam.k;
    cameraRef.current = { k, x: cx - worldX * k, y: cy - worldY * k };
    bumpCam();
  }

  // --- Chat-driven highlighting ---
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());
  const [trail, setTrail] = useState<Array<{ from: string; to: string }>>([]);
  const [flowEdges, setFlowEdges] = useState<Set<string>>(new Set());
  const [cited, setCited] = useState<CitedEntry[]>([]);
  const [pulseId, setPulseId] = useState<string | null>(null);

  function findEdgeKey(a: string, b: string): string | null {
    if (rawEdges.find((l) => l.source === a && l.target === b)) return `${a}→${b}`;
    if (rawEdges.find((l) => l.source === b && l.target === a)) return `${b}→${a}`;
    return null;
  }

  const onCite = useCallback(
    (cite: ChatCite) => {
      const nodeId = `entity:${cite.entity_id}`;
      const node = rawNodes.find((n) => n.id === nodeId);
      if (!node || !sim) return;
      const s = sim.byId.get(nodeId);
      if (!s) return;

      // Spotlight + pulse + trail.
      setHighlighted((prev) => {
        const next = new Set(prev);
        next.add(nodeId);
        return next;
      });
      setPulseId(nodeId);
      window.setTimeout(() => {
        setPulseId((cur) => (cur === nodeId ? null : cur));
      }, 1400);

      setCited((prev) => {
        if (prev.some((c) => c.id === nodeId)) return prev;
        const entry: CitedEntry = {
          id: nodeId,
          name: cite.name,
          cat: cite.entity_type || "entity",
        };
        // Trail from the previous cite to this one if they're directly linked.
        const last = prev[prev.length - 1];
        if (last) {
          const key = findEdgeKey(last.id, nodeId);
          if (key) {
            setFlowEdges((fe) => {
              const nx = new Set(fe);
              nx.add(key);
              return nx;
            });
            window.setTimeout(() => {
              setFlowEdges((fe) => {
                const nx = new Set(fe);
                nx.delete(key);
                return nx;
              });
            }, 1800);
          }
          setTrail((t) => [...t, { from: last.id, to: nodeId }]);
        }
        return [...prev, entry];
      });

      // Pan to the node without zooming out too much.
      const k = Math.max(1.1, cameraRef.current.k);
      const targetX = viewSize.w / 2 - s.x * k;
      const targetY = viewSize.h / 2 - s.y * k;
      animateCamera({ x: targetX, y: targetY, k }, 450);
    },
    [rawNodes, sim, viewSize.w, viewSize.h, rawEdges],
  );

  const onThreadChanged = useCallback(
    (threadId: string | null) => {
      if (!threadId) {
        // Clear highlights on thread end.
        setHighlighted(new Set());
        setTrail([]);
        setFlowEdges(new Set());
        setCited([]);
      }
      void reload();
    },
    [reload],
  );

  // --- Interactions: existing menus/editors ---
  const [editingEntityId, setEditingEntityId] = useState<string | null>(null);
  const [pendingLink, setPendingLink] = useState<PendingLink | null>(null);
  const [pendingNewNode, setPendingNewNode] = useState<PendingNewNode | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerPane, setDrawerPane] = useState<DrawerPane | null>(null);

  const onNodeClick = useCallback(
    (id: string) => {
      if (!sim) return;
      const s = sim.byId.get(id);
      if (!s) return;
      const k = Math.max(1.2, cameraRef.current.k);
      const targetX = viewSize.w / 2 - s.x * k;
      const targetY = viewSize.h / 2 - s.y * k;
      animateCamera({ x: targetX, y: targetY, k }, 400);
      setPulseId(id);
      window.setTimeout(() => setPulseId((cur) => (cur === id ? null : cur)), 1400);
    },
    [sim, viewSize.w, viewSize.h],
  );

  const onNodeDoubleClick = useCallback((id: string) => {
    if (!id.startsWith("entity:")) return;
    setEditingEntityId(id.slice("entity:".length));
  }, []);

  const onPaneDoubleClick = useCallback(
    (flowX: number, flowY: number, screenX: number, screenY: number) => {
      setPendingNewNode({ flowX, flowY, screenX, screenY });
    },
    [],
  );

  const onNodeLink = useCallback(
    (sourceId: string, targetId: string, screenX: number, screenY: number) => {
      if (!sourceId.startsWith("entity:") || !targetId.startsWith("entity:")) return;
      setPendingLink({ source: sourceId, target: targetId, screenX, screenY });
    },
    [],
  );

  const confirmLink = useCallback(
    async (linkType: string) => {
      if (!pendingLink) return;
      const sourceId = pendingLink.source.slice("entity:".length);
      const targetId = pendingLink.target.slice("entity:".length);
      try {
        const link = await api.entityLinks.create({
          source_entity_id: sourceId,
          target_entity_id: targetId,
          link_type: linkType,
        });
        setRawEdges((prev) => [
          ...prev,
          {
            id: `link:${link.id}`,
            source: pendingLink.source,
            target: pendingLink.target,
            edge_type: link.link_type,
            weight: link.weight,
          },
        ]);
      } catch (err) {
        console.error("link create failed", err);
      } finally {
        setPendingLink(null);
      }
    },
    [pendingLink],
  );

  const confirmNewNode = useCallback(
    async (name: string, entityType: string) => {
      if (!pendingNewNode) return;
      try {
        const ent = await api.entities.create({
          canonical_name: name,
          entity_type: entityType,
        });
        const nodeId = `entity:${ent.id}`;
        const newNode: CanvasNode = {
          id: nodeId,
          node_type: "entity",
          label: ent.canonical_name,
          data: {
            entity_type: ent.entity_type,
            has_page: !!ent.page_content,
            overview: ent.page_overview,
            facts_since_render: ent.facts_since_render ?? 0,
          },
          x: pendingNewNode.flowX,
          y: pendingNewNode.flowY,
          width: null,
          height: null,
        };
        setRawNodes((prev) => [...prev, newNode]);
        queueLayout(nodeId, pendingNewNode.flowX, pendingNewNode.flowY);
      } catch (err) {
        console.error("entity create failed", err);
      } finally {
        setPendingNewNode(null);
      }
    },
    [pendingNewNode, queueLayout],
  );

  const onPaletteAction = useCallback(
    (a: PaletteAction) => {
      setPaletteOpen(false);
      if (a.kind === "open-drawer") {
        setDrawerPane(a.pane);
        return;
      }
      if (a.kind === "set-theme") {
        void setTheme(a.theme);
        return;
      }
      if (a.kind === "focus-entity") {
        const nodeId = `entity:${a.id}`;
        if (!sim) return;
        const s = sim.byId.get(nodeId);
        if (!s) return;
        const k = Math.max(1.4, cameraRef.current.k);
        const targetX = viewSize.w / 2 - s.x * k;
        const targetY = viewSize.h / 2 - s.y * k;
        animateCamera({ x: targetX, y: targetY, k }, 500);
        setPulseId(nodeId);
        window.setTimeout(() => setPulseId((cur) => (cur === nodeId ? null : cur)), 1400);
      }
    },
    [setTheme, sim, viewSize.w, viewSize.h],
  );

  const hotkeys = useMemo(
    () => ({
      "cmd+k": (e: KeyboardEvent) => {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      },
      "ctrl+k": (e: KeyboardEvent) => {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      },
    }),
    [],
  );
  useHotkeys(hotkeys);

  if (loading && !rawNodes.length) {
    return (
      <div className="m3-canvas-surface" style={{ padding: 24 }}>
        <div style={{ color: "var(--m3-muted)" }}>Loading canvas…</div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="m3-canvas-surface" style={{ padding: 24 }}>
        <div style={{ color: "oklch(0.72 0.18 18)" }}>Canvas error: {error}</div>
      </div>
    );
  }

  return (
    <div className="m3-canvas-surface" data-variant={variant} ref={viewRef}>
      {sim && graphNodes.length > 0 && (
        <>
          <GraphCanvas
            variant={variant}
            showHulls={true}
            nodes={graphNodes}
            links={graphLinks}
            sim={sim}
            cameraRef={cameraRef}
            cameraVersion={camVer}
            onCameraChange={bumpCam}
            highlighted={highlighted}
            preHighlight={EMPTY_SET}
            trail={trail}
            flowEdges={flowEdges}
            pulseId={pulseId}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onPaneDoubleClick={onPaneDoubleClick}
            onNodeLink={onNodeLink}
            onNodeDragEnd={onNodeDragEnd}
            egoId={egoId}
          />
          <GraphToolbar
            variant={variant}
            setVariant={setVariant}
            zoom={cameraRef.current.k}
            setZoom={setZoom}
            onFit={() => fitTo(sim.state.map((s) => s.id))}
          />
          <div className="m3-bottom-right">
            <GraphLegend />
            <GraphMinimap
              sim={sim}
              camera={cameraRef.current}
              viewSize={viewSize}
              highlighted={highlighted}
              nodeCat={(id) => sim.byId.get(id)?.cat || "entity"}
            />
          </div>
          {cited.length > 0 && (
            <div className="m3-cited-strip">
              <div className="m3-cited-strip__title">Cited, in order</div>
              <ol className="m3-cited-strip__list">
                {cited.map((c, i) => (
                  <li key={c.id}>
                    <button
                      className="m3-cited-item"
                      onClick={() => onNodeClick(c.id)}
                    >
                      <span className="m3-cited-idx">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span
                        className="m3-cited-dot"
                        style={{ background: entityColor(c.cat) }}
                      />
                      <span>{c.name}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}

      {editingEntityId && (
        <NodeEditor
          entityId={editingEntityId}
          onClose={() => setEditingEntityId(null)}
          onSaved={(patch) => {
            const id = `entity:${editingEntityId}`;
            setRawNodes((prev) =>
              prev.map((n) => {
                if (n.id !== id) return n;
                return {
                  ...n,
                  label: patch.canonical_name,
                  data: { ...n.data, has_page: !!patch.page_content },
                };
              }),
            );
          }}
        />
      )}

      {pendingLink && (
        <LinkTypeMenu
          screenX={pendingLink.screenX}
          screenY={pendingLink.screenY}
          onConfirm={confirmLink}
          onCancel={() => setPendingLink(null)}
        />
      )}

      {pendingNewNode && (
        <NewNodeMenu
          screenX={pendingNewNode.screenX}
          screenY={pendingNewNode.screenY}
          onConfirm={confirmNewNode}
          onCancel={() => setPendingNewNode(null)}
        />
      )}

      {paletteOpen && (
        <CommandPalette
          onAction={onPaletteAction}
          onClose={() => setPaletteOpen(false)}
        />
      )}

      <ToolDrawer open={drawerPane} onClose={() => setDrawerPane(null)} />

      <ChatDock onCite={onCite} onThreadChanged={onThreadChanged} />
    </div>
  );
}
