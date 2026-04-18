import { useEffect, useMemo, useRef, useState, MutableRefObject } from "react";
import type { PhysicsSim, PhysicsState } from "./graphPhysics";
import { entityColor, entityHue, linkColor, linkStyle } from "./graphStyle";

export type CanvasVariant = "cosmos" | "blueprint";

export interface GraphNode {
  id: string;
  name: string;
  cat: string;
  overview: string | null;
  facts: number;
  createdAt: string | null;
}

export interface GraphLink {
  s: string;
  t: string;
  type: string;
  createdAt: string | null;
}

export interface CameraRef {
  x: number;
  y: number;
  k: number;
}

export interface GraphCanvasProps {
  variant: CanvasVariant;
  showHulls: boolean;
  nodes: GraphNode[];
  links: GraphLink[];
  sim: PhysicsSim;
  cameraRef: MutableRefObject<CameraRef>;
  cameraVersion: number;
  onCameraChange: () => void;
  highlighted: Set<string>;
  preHighlight: Set<string>;
  trail: Array<{ from: string; to: string }>;
  flowEdges: Set<string>;
  pulseId: string | null;
  onNodeClick: (id: string) => void;
  onNodeDoubleClick?: (id: string) => void;
  onPaneDoubleClick?: (flowX: number, flowY: number, screenX: number, screenY: number) => void;
  onNodeLink?: (sourceId: string, targetId: string, screenX: number, screenY: number) => void;
  onNodeDragEnd?: (id: string, x: number, y: number) => void;
  egoId?: string | null;
  timeCutoff?: string | null; // ISO date; nodes/edges created after this are hidden
}

export default function GraphCanvas(props: GraphCanvasProps) {
  const {
    variant,
    showHulls,
    nodes,
    links,
    sim,
    cameraRef,
    cameraVersion: _cameraVersion,
    onCameraChange,
    highlighted,
    preHighlight,
    trail,
    flowEdges,
    pulseId,
    onNodeClick,
    onNodeDoubleClick,
    onPaneDoubleClick,
    onNodeLink,
    onNodeDragEnd,
    egoId,
    timeCutoff,
  } = props;

  // A node or edge is visible iff its createdAt is ≤ cutoff, or we have no
  // cutoff at all, or the item's createdAt is unknown (don't hide data
  // without a timestamp — user would lose it entirely).
  const visibleAt = (iso: string | null) =>
    !timeCutoff || !iso || iso.slice(0, 10) <= timeCutoff;

  void _cameraVersion;

  const ref = useRef<HTMLDivElement>(null);
  const [hoverEdge, setHoverEdge] = useState<number | null>(null);
  // Tracks start node when user is building a link via shift-drag between nodes.
  const linkStartIdRef = useRef<string | null>(null);
  const [linkGhost, setLinkGhost] = useState<{ startId: string; x: number; y: number } | null>(
    null,
  );

  const nodesById = useMemo(() => {
    const m = new Map<string, GraphNode>();
    nodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [nodes]);

  const onCameraRef = useRef(onCameraChange);
  const onNodeClickRef = useRef(onNodeClick);
  const onNodeDoubleClickRef = useRef(onNodeDoubleClick);
  const onPaneDoubleClickRef = useRef(onPaneDoubleClick);
  const onNodeLinkRef = useRef(onNodeLink);
  const onNodeDragEndRef = useRef(onNodeDragEnd);
  useEffect(() => {
    onCameraRef.current = onCameraChange;
  }, [onCameraChange]);
  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);
  useEffect(() => {
    onNodeDoubleClickRef.current = onNodeDoubleClick;
  }, [onNodeDoubleClick]);
  useEffect(() => {
    onPaneDoubleClickRef.current = onPaneDoubleClick;
  }, [onPaneDoubleClick]);
  useEffect(() => {
    onNodeLinkRef.current = onNodeLink;
  }, [onNodeLink]);
  useEffect(() => {
    onNodeDragEndRef.current = onNodeDragEnd;
  }, [onNodeDragEnd]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const el: HTMLDivElement = node;
    let panning = false;
    let sx = 0,
      sy = 0;
    let startCam: CameraRef | null = null;
    let draggingNodeId: string | null = null;
    let didDrag = false;
    let downPos: { x: number; y: number } | null = null;
    let lastClick = 0;
    let lastClickId: string | null = null;
    let linkingFromId: string | null = null;

    function hitTestNode(worldX: number, worldY: number): PhysicsState | null {
      const cam = cameraRef.current;
      const hitR = 32 / cam.k;
      const hitR2 = hitR * hitR;
      let hit: PhysicsState | null = null;
      let hitD2 = Infinity;
      for (const s of sim.state) {
        const dx = s.x - worldX,
          dy = s.y - worldY;
        const d2 = dx * dx + dy * dy;
        if (d2 < hitR2 && d2 < hitD2) {
          hit = s;
          hitD2 = d2;
        }
      }
      return hit;
    }

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const worldX = (mx - cam.x) / cam.k;
      const worldY = (my - cam.y) / cam.k;
      const factor = Math.exp(-e.deltaY * 0.0015);
      const newK = Math.max(0.2, Math.min(3.5, cam.k * factor));
      cam.k = newK;
      cam.x = mx - worldX * newK;
      cam.y = my - worldY * newK;
      onCameraRef.current?.();
    }

    function onDown(e: MouseEvent) {
      if (e.button !== 0) return;
      downPos = { x: e.clientX, y: e.clientY };
      didDrag = false;
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left,
        my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
      const hit = hitTestNode(world.x, world.y);

      if (hit && e.shiftKey) {
        // Start a link-draw from this node.
        linkingFromId = hit.id;
        linkStartIdRef.current = hit.id;
        setLinkGhost({ startId: hit.id, x: world.x, y: world.y });
        e.preventDefault();
        return;
      }

      if (hit && !hit.pinned) {
        draggingNodeId = hit.id;
        sim.setDrag(hit.id, world.x, world.y);
        el.style.cursor = "grabbing";
        e.preventDefault();
      } else if (hit && hit.pinned) {
        draggingNodeId = "__pinned__" + hit.id;
        e.preventDefault();
      } else {
        panning = true;
        sx = e.clientX;
        sy = e.clientY;
        startCam = { ...cam };
        el.style.cursor = "grabbing";
      }
    }

    function onMove(e: MouseEvent) {
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left,
        my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
      const overCanvas = mx >= 0 && my >= 0 && mx <= rect.width && my <= rect.height;
      sim.setMouse(world.x, world.y, overCanvas && !draggingNodeId && !linkingFromId);
      if (downPos && Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 4)
        didDrag = true;
      if (linkingFromId) {
        setLinkGhost({ startId: linkingFromId, x: world.x, y: world.y });
      } else if (draggingNodeId && !draggingNodeId.startsWith("__pinned__")) {
        sim.updateDragTarget(world.x, world.y);
      } else if (panning && startCam) {
        cam.x = startCam.x + (e.clientX - sx);
        cam.y = startCam.y + (e.clientY - sy);
        onCameraRef.current?.();
      }
    }

    function onUp(e: MouseEvent) {
      if (linkingFromId) {
        const rect = el.getBoundingClientRect();
        const mx = e.clientX - rect.left,
          my = e.clientY - rect.top;
        const cam = cameraRef.current;
        const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
        const endHit = hitTestNode(world.x, world.y);
        if (endHit && endHit.id !== linkingFromId) {
          onNodeLinkRef.current?.(linkingFromId, endHit.id, e.clientX, e.clientY);
        }
        linkingFromId = null;
        linkStartIdRef.current = null;
        setLinkGhost(null);
        el.style.cursor = "grab";
        downPos = null;
        return;
      }

      if (draggingNodeId) {
        const id = draggingNodeId.startsWith("__pinned__")
          ? draggingNodeId.slice("__pinned__".length)
          : draggingNodeId;
        const wasPinned = draggingNodeId.startsWith("__pinned__");
        sim.releaseDrag();
        if (!didDrag) {
          const now = performance.now();
          const isDbl = now - lastClick < 280 && lastClickId === id;
          if (isDbl) {
            onNodeDoubleClickRef.current?.(id);
            lastClick = 0;
            lastClickId = null;
          } else {
            onNodeClickRef.current?.(id);
            lastClick = now;
            lastClickId = id;
          }
        } else if (!wasPinned) {
          const s = sim.byId.get(id);
          if (s) onNodeDragEndRef.current?.(id, s.x, s.y);
        }
      }
      draggingNodeId = null;
      panning = false;
      startCam = null;
      downPos = null;
      el.style.cursor = "grab";
    }

    function onLeave() {
      sim.setMouse(0, 0, false);
    }

    function onDblClick(e: MouseEvent) {
      // Only fire for empty-pane dblclicks.
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left,
        my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
      const hit = hitTestNode(world.x, world.y);
      if (hit) return;
      onPaneDoubleClickRef.current?.(world.x, world.y, e.clientX, e.clientY);
    }

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    el.addEventListener("mouseleave", onLeave);
    el.addEventListener("dblclick", onDblClick);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      el.removeEventListener("mouseleave", onLeave);
      el.removeEventListener("dblclick", onDblClick);
    };
  }, [sim, cameraRef]);

  const cam = cameraRef.current;
  const k = cam.k;
  const lodCard = k > 1.4;
  // Labels show much earlier than the prototype's 0.55 — the live graph has
  // far more nodes than the mocked demo, so the default fit sits around 30-40%
  // zoom and the user needs at least names to read what's on screen.
  const lodLabel = k > 0.32;

  const hasHL = highlighted && highlighted.size > 0;

  const hulls = useMemo(() => {
    const byCat = new Map<string, PhysicsState[]>();
    sim.state.forEach((s) => {
      if (!byCat.has(s.cat)) byCat.set(s.cat, []);
      byCat.get(s.cat)!.push(s);
    });
    const out: Array<{ cat: string; cx: number; cy: number; r: number }> = [];
    for (const [cat, arr] of byCat) {
      if (arr.length < 2) continue;
      let cx = 0,
        cy = 0;
      arr.forEach((a) => {
        cx += a.x;
        cy += a.y;
      });
      cx /= arr.length;
      cy /= arr.length;
      let r = 0;
      arr.forEach((a) => {
        const d = Math.hypot(a.x - cx, a.y - cy);
        if (d > r) r = d;
      });
      out.push({ cat, cx, cy, r: r + 70 });
    }
    return out;
    // sim.state mutates in place each tick; callers bump cameraVersion to redraw.
  }, [sim.state, _cameraVersion]);

  const camStyle = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;

  const uniqueLinkTypes = useMemo(() => {
    const seen = new Set<string>();
    links.forEach((l) => seen.add(l.type));
    return Array.from(seen);
  }, [links]);

  const startForGhost = linkGhost ? sim.byId.get(linkGhost.startId) : null;

  return (
    <div ref={ref} className="m3-graph" style={{ cursor: "grab" }}>
      <svg width="100%" height="100%" style={{ display: "block" }}>
        <defs>
          <radialGradient id="m3-node-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="white" stopOpacity="0.8" />
            <stop offset="60%" stopColor="white" stopOpacity="0.12" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          {uniqueLinkTypes.map((t) => (
            <marker
              key={t}
              id={`m3-arrow-${cssId(t)}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={linkColor(t, 0.9)} />
            </marker>
          ))}
          <filter id="m3-soft-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g style={{ transform: camStyle, transformOrigin: "0 0" }}>
          {showHulls && variant === "cosmos" &&
            hulls.map((h) => (
              <circle
                key={h.cat}
                cx={h.cx}
                cy={h.cy}
                r={h.r}
                fill={entityColor(h.cat, 0.035)}
                stroke={entityColor(h.cat, 0.18)}
                strokeDasharray="2 6"
                strokeWidth={1}
              />
            ))}
          {showHulls && variant === "blueprint" &&
            hulls.map((h) => (
              <g key={h.cat}>
                <rect
                  x={h.cx - h.r}
                  y={h.cy - h.r}
                  width={h.r * 2}
                  height={h.r * 2}
                  fill="none"
                  stroke={entityColor(h.cat, 0.22)}
                  strokeDasharray="2 4"
                  strokeWidth={1}
                />
                <text
                  x={h.cx - h.r + 8}
                  y={h.cy - h.r + 14}
                  fill={entityColor(h.cat, 0.85)}
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="10"
                  style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
                >
                  {h.cat}
                </text>
              </g>
            ))}

          {links.map((l, i) => {
            const a = sim.byId.get(l.s);
            const b = sim.byId.get(l.t);
            if (!a || !b) return null;
            if (!visibleAt(l.createdAt)) return null;
            const aNode = nodesById.get(l.s);
            const bNode = nodesById.get(l.t);
            if (aNode && !visibleAt(aNode.createdAt)) return null;
            if (bNode && !visibleAt(bNode.createdAt)) return null;

            const key = `${l.s}→${l.t}`;
            const isFlowing = flowEdges.has(key);
            const isHL = hasHL && highlighted.has(l.s) && highlighted.has(l.t);
            const dim = hasHL && !isHL;
            const hover = hoverEdge === i;

            const base = linkColor(l.type, dim ? 0.08 : isHL ? 1 : 0.45);
            const sw = isHL ? 2.2 : isFlowing ? 2 : 1;
            const def = linkStyle(l.type);
            const dash = def.dash ?? undefined;

            const ra = nodeRadius(l.s, a.degree, egoId) + 4;
            const rb = nodeRadius(l.t, b.degree, egoId) + 4;
            const edx = b.x - a.x,
              edy = b.y - a.y;
            const elen = Math.hypot(edx, edy) || 1;
            const ax = a.x + (edx / elen) * ra;
            const ay = a.y + (edy / elen) * ra;
            const bx = b.x - (edx / elen) * rb;
            const by = b.y - (edy / elen) * rb;

            const mx = (ax + bx) / 2;
            const my = (ay + by) / 2;
            const dx = bx - ax,
              dy = by - ay;
            const nx = -dy,
              ny = dx;
            const nlen = Math.hypot(nx, ny) || 1;
            const curve = variant === "cosmos" ? 0.12 : 0.04;
            const offset = Math.hypot(dx, dy) * curve;
            const qx = mx + (nx / nlen) * offset;
            const qy = my + (ny / nlen) * offset;
            const d = `M ${ax} ${ay} Q ${qx} ${qy} ${bx} ${by}`;

            return (
              <g key={i}>
                <path
                  d={d}
                  fill="none"
                  stroke={base}
                  strokeWidth={sw}
                  strokeDasharray={dash}
                  filter={
                    (isHL || isFlowing) && variant === "cosmos" ? "url(#m3-soft-glow)" : undefined
                  }
                  style={{ transition: "stroke 220ms, stroke-width 220ms, opacity 220ms" }}
                />
                {isFlowing && (
                  <path
                    d={d}
                    fill="none"
                    stroke={linkColor(l.type, 1)}
                    strokeWidth={sw + 1}
                    strokeDasharray="8 18"
                    style={{ animation: "m3-flow 1.2s linear infinite" }}
                    filter="url(#m3-soft-glow)"
                  />
                )}
                <path
                  d={d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={14}
                  onMouseEnter={() => setHoverEdge(i)}
                  onMouseLeave={() => setHoverEdge(null)}
                  style={{ pointerEvents: "stroke", cursor: "help" }}
                />
                {(hover || isHL) && lodLabel && (
                  <g transform={`translate(${qx}, ${qy})`} style={{ pointerEvents: "none" }}>
                    <rect
                      x={-52}
                      y={-9}
                      width={104}
                      height={18}
                      rx={2}
                      fill="oklch(0.18 0.01 260)"
                      stroke={linkColor(l.type, 0.8)}
                      strokeWidth={0.8}
                    />
                    <text
                      textAnchor="middle"
                      y={3}
                      fill={linkColor(l.type, 1)}
                      fontFamily="'JetBrains Mono', monospace"
                      fontSize="9"
                      style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
                    >
                      {def.label}
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {trail.map((seg, i) => {
            const a = sim.byId.get(seg.from);
            const b = sim.byId.get(seg.to);
            if (!a || !b) return null;
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="oklch(0.92 0.08 80)"
                strokeWidth={1.5}
                strokeDasharray="2 6"
                opacity={0.9}
                filter="url(#m3-soft-glow)"
              />
            );
          })}

          {linkGhost && startForGhost && (
            <line
              x1={startForGhost.x}
              y1={startForGhost.y}
              x2={linkGhost.x}
              y2={linkGhost.y}
              stroke="oklch(0.92 0.08 80)"
              strokeWidth={1.2}
              strokeDasharray="3 4"
              opacity={0.85}
            />
          )}

          {[...sim.state]
            .sort((a, b) => (a.id === egoId ? 1 : 0) - (b.id === egoId ? 1 : 0))
            .map((s) => {
              const n = nodesById.get(s.id);
              if (!n) return null;
              if (!visibleAt(n.createdAt)) return null;
              const hl = hasHL && highlighted.has(s.id);
              const dim = hasHL && !hl;
              const pre = preHighlight && preHighlight.has(s.id);
              const isPulse = pulseId === s.id;
              const r = nodeRadius(s.id, s.degree, egoId);
              return (
                <NodeMark
                  key={s.id}
                  node={n}
                  s={s}
                  variant={variant}
                  hl={hl}
                  dim={dim}
                  pre={pre}
                  isPulse={isPulse}
                  lodCard={lodCard}
                  lodLabel={lodLabel}
                  radius={r}
                  isEgo={s.id === egoId}
                />
              );
            })}
        </g>
      </svg>
    </div>
  );
}

function nodeRadius(id: string, degree: number, egoId: string | null | undefined): number {
  if (id === egoId) return 32;
  return 8 + Math.sqrt(Math.max(degree, 1)) * 3;
}

function cssId(s: string): string {
  return s.replace(/[^a-z0-9_-]/gi, "_");
}

interface NodeMarkProps {
  node: GraphNode;
  s: PhysicsState;
  variant: CanvasVariant;
  hl: boolean;
  dim: boolean;
  pre: boolean;
  isPulse: boolean;
  lodCard: boolean;
  lodLabel: boolean;
  radius: number;
  isEgo: boolean;
}

function NodeMark({
  node,
  s,
  variant,
  hl,
  dim,
  pre,
  isPulse,
  lodCard,
  lodLabel,
  radius,
  isEgo,
}: NodeMarkProps) {
  const color = entityColor(node.cat, 1);
  const colorDim = entityColor(node.cat, 0.25);
  const fill = variant === "cosmos" ? "oklch(0.22 0.012 260)" : "oklch(0.20 0.01 260)";
  const egoHue = entityHue(node.cat);

  return (
    <g
      data-node={node.id}
      transform={`translate(${s.x}, ${s.y})`}
      style={{
        cursor: s.pinned ? "default" : "grab",
        opacity: dim ? 0.22 : 1,
        transition: "opacity 220ms",
      }}
    >
      {variant === "cosmos" && (hl || isPulse) && (
        <circle r={radius + 18} fill="url(#m3-node-halo)" opacity={hl ? 0.6 : 0.4} />
      )}
      {isPulse && (
        <circle
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={2}
          style={{ animation: "m3-pulse 1.4s ease-out" }}
        />
      )}
      {pre && !hl && (
        <circle
          r={radius + 5}
          fill="none"
          stroke={color}
          strokeWidth={1}
          strokeDasharray="2 3"
          opacity={0.7}
        />
      )}

      {variant === "cosmos" ? (
        isEgo ? (
          <>
            <circle
              r={radius + 24}
              fill="none"
              stroke={color}
              strokeWidth={0.8}
              strokeDasharray="1 4"
              opacity={0.55}
            />
            <circle
              r={radius + 10}
              fill="none"
              stroke={color}
              strokeWidth={0.6}
              opacity={0.4}
            />
            <circle
              r={radius}
              fill={`oklch(0.26 0.06 ${egoHue})`}
              stroke={color}
              strokeWidth={1.5}
              filter="url(#m3-soft-glow)"
            />
            <text
              textAnchor="middle"
              y={6}
              fill="oklch(0.98 0.005 260)"
              fontFamily="Inter, system-ui, sans-serif"
              fontSize={radius * 0.7}
              fontWeight={600}
              style={{ pointerEvents: "none" }}
            >
              {node.name[0] || "·"}
            </text>
          </>
        ) : (
          <>
            <circle
              r={radius}
              fill={fill}
              stroke={hl ? color : colorDim}
              strokeWidth={hl ? 2 : 1}
              filter={hl ? "url(#m3-soft-glow)" : undefined}
            />
            <circle r={radius * 0.4} fill={hl ? color : colorDim} />
          </>
        )
      ) : isEgo ? (
        <>
          <rect
            x={-radius}
            y={-radius}
            width={radius * 2}
            height={radius * 2}
            fill={`oklch(0.24 0.05 ${egoHue})`}
            stroke={color}
            strokeWidth={1.4}
          />
          <rect
            x={-radius + 4}
            y={-radius + 4}
            width={radius * 2 - 8}
            height={radius * 2 - 8}
            fill="none"
            stroke={color}
            strokeWidth={0.5}
            opacity={0.5}
          />
          <text
            textAnchor="middle"
            y={5}
            fill="oklch(0.98 0.005 260)"
            fontFamily="'JetBrains Mono', monospace"
            fontSize={radius * 0.6}
            fontWeight={600}
            style={{ pointerEvents: "none", letterSpacing: "0.04em" }}
          >
            {node.name[0] || "·"}
          </text>
        </>
      ) : (
        <>
          <rect
            x={-radius}
            y={-radius}
            width={radius * 2}
            height={radius * 2}
            fill={fill}
            stroke={hl ? color : colorDim}
            strokeWidth={hl ? 1.6 : 1}
          />
          <rect
            x={-radius + 3}
            y={-radius + 3}
            width={radius * 2 - 6}
            height={2}
            fill={hl ? color : colorDim}
            opacity={0.6}
          />
        </>
      )}

      {lodLabel && !lodCard && !isEgo && (
        <g transform={`translate(0, ${radius + 14})`} style={{ pointerEvents: "none" }}>
          <text
            textAnchor="middle"
            fill={hl ? "oklch(0.98 0.005 260)" : "oklch(0.78 0.01 260)"}
            fontFamily="Inter, system-ui, sans-serif"
            fontSize="11"
            fontWeight={hl ? 600 : 500}
          >
            {node.name}
          </text>
        </g>
      )}
      {lodCard && (
        <g transform={`translate(${radius + 10}, ${-radius})`} style={{ pointerEvents: "none" }}>
          <rect
            x={0}
            y={0}
            width={220}
            height={68}
            rx={variant === "cosmos" ? 8 : 0}
            fill="oklch(0.22 0.012 260 / 0.96)"
            stroke={hl ? color : "oklch(0.3 0.008 260)"}
            strokeWidth={hl ? 1.2 : 1}
          />
          <text
            x={12}
            y={20}
            fill="oklch(0.96 0.005 260)"
            fontFamily="Inter, system-ui, sans-serif"
            fontSize="12"
            fontWeight={600}
          >
            {truncate(node.name, 24)}
          </text>
          <text
            x={12}
            y={34}
            fill={color}
            fontFamily="'JetBrains Mono', monospace"
            fontSize="9"
            style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
          >
            {node.cat} · {node.facts} facts
          </text>
          <foreignObject x={12} y={38} width={200} height={26}>
            <div
              style={{
                fontFamily: "Inter, system-ui, sans-serif",
                fontSize: 10.5,
                lineHeight: 1.3,
                color: "oklch(0.72 0.01 260)",
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              {node.overview || ""}
            </div>
          </foreignObject>
        </g>
      )}
    </g>
  );
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}
