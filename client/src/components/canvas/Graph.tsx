// SVG-rendered force-directed knowledge graph. Owns the camera (pan/zoom)
// and node-drag interactions; pulls layout positions from a Layout instance
// that's stepped by an external RAF loop in Canvas.tsx.
//
// Three highlight states stack visually:
//   - `pre`     : subtle dashed ring while user is typing a query
//   - `hl`      : hard highlight (cited or selected)
//   - `pulse`   : transient ring expanding outward on a fresh citation
// And the inverse `dim` state quiets every other node to ~22% opacity when
// any highlight set is active, so cited subgraphs read clearly.

import { useEffect, useMemo, useRef } from "react";
import { catColor, linkColor, type Category, type LinkKind, LINK_STYLE } from "../../lib/canvasColors";
import type { Layout } from "../../lib/forceLayout";
import { NodeMark, type DisplayNode, type Variant } from "./NodeMark";

export interface GraphLink {
  s: string;
  t: string;
  kind: LinkKind;
}

export interface GraphHull {
  cat: Category;
  cx: number;
  cy: number;
  r: number;
}

export interface GraphProps {
  layout: Layout;
  nodes: DisplayNode[];
  links: GraphLink[];
  variant: Variant;
  showHulls: boolean;
  highlighted: Set<string>;
  preHighlighted: Set<string>;
  pulseId: string | null;
  flowEdges: Set<string>;        // `${s}→${t}` keys for the citation flow animation
  cameraRef: React.MutableRefObject<{ x: number; y: number; k: number }>;
  onCamera: () => void;
  onNodeClick?: (id: string) => void;
  /** Bumps when camera changes — React re-renders so the transform style updates. */
  cameraVersion: number;
}

export function Graph({
  layout, nodes, links, variant, showHulls,
  highlighted, preHighlighted, pulseId, flowEdges,
  cameraRef, onCamera, onNodeClick, cameraVersion,
}: GraphProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Stable refs so interaction listeners don't re-attach every render.
  const onCameraRef = useRef(onCamera);
  const onNodeClickRef = useRef(onNodeClick);
  useEffect(() => { onCameraRef.current = onCamera; }, [onCamera]);
  useEffect(() => { onNodeClickRef.current = onNodeClick; }, [onNodeClick]);

  // Pan / zoom / drag wiring — installed once.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    let panning = false;
    let sx = 0, sy = 0;
    let startCam: { x: number; y: number; k: number } | null = null;
    let draggingId: string | null = null;
    let didDrag = false;
    let downPos: { x: number; y: number } | null = null;

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const wx = (mx - cam.x) / cam.k;
      const wy = (my - cam.y) / cam.k;
      const factor = Math.exp(-e.deltaY * 0.0015);
      const newK = Math.max(0.25, Math.min(3.5, cam.k * factor));
      cam.k = newK;
      cam.x = mx - wx * newK;
      cam.y = my - wy * newK;
      onCameraRef.current();
    }

    function onDown(e: MouseEvent) {
      if (e.button !== 0) return;
      downPos = { x: e.clientX, y: e.clientY };
      didDrag = false;
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
      // Hit-test nearest layout node within 28 screen-px
      const hitR = 28 / cam.k;
      const hitR2 = hitR * hitR;
      let hit: typeof layout.state[number] | null = null;
      let hitD2 = Infinity;
      for (const s of layout.state) {
        const dx = s.x - world.x;
        const dy = s.y - world.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < hitR2 && d2 < hitD2) { hit = s; hitD2 = d2; }
      }
      if (hit && !hit.pinned) {
        draggingId = hit.id;
        layout.setDrag(hit.id, world.x, world.y);
        el!.style.cursor = "grabbing";
        e.preventDefault();
      } else if (hit && hit.pinned) {
        // Click without drag fires onNodeClick (e.g. focusing the ego)
        draggingId = "__pinned__" + hit.id;
        e.preventDefault();
      } else {
        panning = true;
        sx = e.clientX; sy = e.clientY;
        startCam = { ...cam };
        el!.style.cursor = "grabbing";
      }
    }

    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cam = cameraRef.current;
      const world = { x: (mx - cam.x) / cam.k, y: (my - cam.y) / cam.k };
      const overCanvas = mx >= 0 && my >= 0 && mx <= rect.width && my <= rect.height;
      layout.setMouse(world.x, world.y, overCanvas && !draggingId);
      if (downPos && Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 4) didDrag = true;
      if (draggingId && !draggingId.startsWith("__pinned__")) {
        layout.updateDragTarget(world.x, world.y);
      } else if (panning && startCam) {
        cam.x = startCam.x + (e.clientX - sx);
        cam.y = startCam.y + (e.clientY - sy);
        onCameraRef.current();
      }
    }

    function onUp() {
      if (draggingId) {
        const id = draggingId.startsWith("__pinned__")
          ? draggingId.slice("__pinned__".length)
          : draggingId;
        layout.releaseDrag();
        if (!didDrag) onNodeClickRef.current?.(id);
      }
      draggingId = null;
      panning = false;
      startCam = null;
      downPos = null;
      el!.style.cursor = "grab";
    }

    function onLeave() { layout.setMouse(0, 0, false); }

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [layout, cameraRef]);

  const nodeById = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes]);

  const hulls = useMemo<GraphHull[]>(() => {
    const byCat = new Map<Category, typeof layout.state>();
    for (const s of layout.state) {
      const arr = byCat.get(s.cat) ?? [];
      arr.push(s);
      byCat.set(s.cat, arr);
    }
    const out: GraphHull[] = [];
    byCat.forEach((arr, cat) => {
      if (arr.length < 2) return;
      let cx = 0, cy = 0;
      for (const a of arr) { cx += a.x; cy += a.y; }
      cx /= arr.length; cy /= arr.length;
      let r = 0;
      for (const a of arr) {
        const d = Math.hypot(a.x - cx, a.y - cy);
        if (d > r) r = d;
      }
      out.push({ cat, cx, cy, r: r + 70 });
    });
    return out;
    // We intentionally re-compute on every cameraVersion bump too: the
    // physics step drifts node positions every RAF, so hulls follow.
  }, [layout, cameraVersion]);

  const cam = cameraRef.current;
  const camStyle = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;
  const hasHL = highlighted.size > 0;
  const lodCard = cam.k > 1.2;
  const lodLabel = cam.k > 0.55;

  return (
    <div
      ref={rootRef}
      className="m3-canvas"
      style={{ position: "absolute", inset: 0, overflow: "hidden", cursor: "grab" }}
    >
      <svg width="100%" height="100%" style={{ display: "block" }}>
        <defs>
          <radialGradient id="m3-node-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="white" stopOpacity="0.8" />
            <stop offset="60%" stopColor="white" stopOpacity="0.12" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <filter id="m3-soft-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g style={{ transform: camStyle, transformOrigin: "0 0" }}>
          {showHulls && variant === "cosmos" && hulls.map(h => (
            <circle
              key={h.cat}
              cx={h.cx}
              cy={h.cy}
              r={h.r}
              fill={catColor(h.cat, 0.035)}
              stroke={catColor(h.cat, 0.18)}
              strokeDasharray="2 6"
              strokeWidth={1}
            />
          ))}
          {showHulls && variant === "blueprint" && hulls.map(h => (
            <g key={h.cat}>
              <rect
                x={h.cx - h.r}
                y={h.cy - h.r}
                width={h.r * 2}
                height={h.r * 2}
                fill="none"
                stroke={catColor(h.cat, 0.22)}
                strokeDasharray="2 4"
                strokeWidth={1}
              />
              <text
                x={h.cx - h.r + 8}
                y={h.cy - h.r + 14}
                fill={catColor(h.cat, 0.85)}
                fontFamily="'JetBrains Mono', monospace"
                fontSize="10"
                style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
              >
                {h.cat}
              </text>
            </g>
          ))}

          {/* Edges */}
          {links.map((l, i) => {
            const a = layout.byId.get(l.s);
            const b = layout.byId.get(l.t);
            if (!a || !b) return null;
            const isHL = hasHL && highlighted.has(l.s) && highlighted.has(l.t);
            const dim = hasHL && !isHL;
            const key = `${l.s}→${l.t}`;
            const isFlowing = flowEdges.has(key);
            const base = linkColor(l.kind, dim ? 0.08 : isHL ? 1 : 0.45);
            const sw = isHL ? 2.2 : isFlowing ? 2 : 1;
            const dash = LINK_STYLE[l.kind].dash || undefined;

            // Trim endpoints to the node disc so arrows don't visually overlap nodes.
            const ra = (nodeById.get(l.s)?.isEgo ? 32 : 8 + Math.sqrt(a.degree || 1) * 3) + 4;
            const rb = (nodeById.get(l.t)?.isEgo ? 32 : 8 + Math.sqrt(b.degree || 1) * 3) + 4;
            const edx = b.x - a.x, edy = b.y - a.y;
            const elen = Math.hypot(edx, edy) || 1;
            const ax = a.x + (edx / elen) * ra;
            const ay = a.y + (edy / elen) * ra;
            const bx = b.x - (edx / elen) * rb;
            const by = b.y - (edy / elen) * rb;
            const mx = (ax + bx) / 2;
            const my = (ay + by) / 2;
            const dx = bx - ax, dy = by - ay;
            const nx = -dy, ny = dx;
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
                  filter={(isHL || isFlowing) && variant === "cosmos" ? "url(#m3-soft-glow)" : undefined}
                  style={{ transition: "stroke 220ms, stroke-width 220ms, opacity 220ms" }}
                />
                {isFlowing && (
                  <path
                    d={d}
                    fill="none"
                    stroke={linkColor(l.kind, 1)}
                    strokeWidth={sw + 1}
                    strokeDasharray="8 18"
                    style={{ animation: "m3-flow 1.2s linear infinite" }}
                    filter="url(#m3-soft-glow)"
                  />
                )}
              </g>
            );
          })}

          {/* Nodes — render ego last so it sits on top */}
          {[...layout.state]
            .sort((a, b) => Number(nodeById.get(a.id)?.isEgo ?? false) - Number(nodeById.get(b.id)?.isEgo ?? false))
            .map(s => {
              const n = nodeById.get(s.id);
              if (!n) return null;
              const hl = hasHL && highlighted.has(s.id);
              const dim = hasHL && !hl;
              const pre = preHighlighted.has(s.id);
              const pulse = pulseId === s.id;
              const r = n.isEgo ? 32 : 8 + Math.sqrt(s.degree) * 3;
              return (
                <NodeMark
                  key={s.id}
                  node={n}
                  x={s.x}
                  y={s.y}
                  radius={r}
                  variant={variant}
                  hl={hl}
                  dim={dim}
                  pre={pre}
                  pulse={pulse}
                  showLabel={lodLabel}
                  showCard={lodCard}
                />
              );
            })}
        </g>
      </svg>
    </div>
  );
}
