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
import { linkColor, type LinkKind, LINK_STYLE } from "../../lib/canvasColors";
import type { Layout } from "../../lib/forceLayout";
import { NodeMark, type DisplayNode, type Variant } from "./NodeMark";

export interface GraphLink {
  s: string;
  t: string;
  kind: LinkKind;
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
  /** Click on empty canvas (didn't hit a node and didn't pan). Used to clear
   *  focus mode without forcing the user to find an Esc key or close button. */
  onCanvasClick?: () => void;
  /** Bumps when camera changes — React re-renders so the transform style updates. */
  cameraVersion: number;
  /** Canvas v2 mode: concentric recency rings + no pinned ego + multi-resolution
   *  zoom gating on nodes (handled in NodeMark). When false (default), the
   *  existing radial-by-type layout renders unchanged. */
  v2?: boolean;
  /** Canvas v2: id of the currently expanded claim card (or null). Forwarded
   *  to NodeMark so the matching pill renders an attached ClaimCard. */
  expandedClaimId?: string | null;
  /** Canvas v2: invoked from a claim pill click. Canvas owns the toggle so
   *  only one card can be open at a time. */
  onClaimToggle?: (id: string) => void;
}

export function Graph({
  layout, nodes, links, variant, showHulls,
  highlighted, preHighlighted, pulseId, flowEdges,
  cameraRef, onCamera, onNodeClick, onCanvasClick, cameraVersion: _cameraVersion,
  v2 = false, expandedClaimId = null, onClaimToggle,
}: GraphProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Stable refs so interaction listeners don't re-attach every render.
  const onCameraRef = useRef(onCamera);
  const onNodeClickRef = useRef(onNodeClick);
  const onCanvasClickRef = useRef(onCanvasClick);
  useEffect(() => { onCameraRef.current = onCamera; }, [onCamera]);
  useEffect(() => { onNodeClickRef.current = onNodeClick; }, [onNodeClick]);
  useEffect(() => { onCanvasClickRef.current = onCanvasClick; }, [onCanvasClick]);

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
      } else if (panning && !didDrag) {
        // Pure click on empty canvas: tell Canvas to clear focus.
        onCanvasClickRef.current?.();
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

  // hulls were used by the old force-directed layout to outline category
  // clusters — redundant now that nodes are deterministically slotted on
  // labeled rings.

  const cam = cameraRef.current;
  const camStyle = `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`;
  const hasHL = highlighted.size > 0;
  // Inline detail cards are gone — they overlapped each other unreadably
  // when nodes sat close. The DetailPanel on the right is the single source
  // of truth for full content now. Labels still appear at moderate zoom.
  const lodCard = false;
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
          {/* Concentric ring guides at the radial bands. Drawn first so
            * everything else (edges, nodes) sits on top. Faint enough to
            * read as orientation, not as content. */}
          {v2 ? (() => {
            // Canvas v2: concentric recency rings centered on the canvas.
            // Replaces the radial-by-type guides; the center is "now," outer
            // rings are older. Radii match the forceLayout v2 targets.
            const cx = layout.width / 2;
            const cy = layout.height / 2;
            const labelFill = "oklch(0.55 0.02 260 / 0.6)";
            const rings: { r: number; label: string; alpha: number }[] = [
              { r: 140, label: "THIS WEEK",    alpha: 0.70 },
              { r: 260, label: "THIS MONTH",   alpha: 0.40 },
              { r: 420, label: "THIS QUARTER", alpha: 0.22 },
              { r: 600, label: "EARLIER",      alpha: 0.13 },
            ];
            return rings.map(ring => (
              <g key={ring.r}>
                <circle
                  cx={cx} cy={cy} r={ring.r}
                  fill="none"
                  stroke={`oklch(0.5 0.02 260 / ${ring.alpha})`}
                  strokeDasharray="3 6"
                  strokeWidth={1}
                />
                <text
                  x={cx} y={cy - ring.r - 6}
                  fill={labelFill}
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="9"
                  textAnchor="middle"
                  style={{ letterSpacing: "0.18em", textTransform: "uppercase" }}
                >
                  {ring.label}
                </text>
              </g>
            ));
          })() : (
            showHulls && (() => {
              const ego = layout.state.find(s => s.pinned);
              if (!ego) return null;
              const stroke = variant === "cosmos" ? "oklch(0.45 0.01 260 / 0.18)" : "oklch(0.45 0.01 260 / 0.28)";
              const labelFill = "oklch(0.5 0.01 260 / 0.6)";
              const rings = [
                { r: 230, label: "syntheses" },
                { r: 380, label: "entities" },
                { r: 560, label: "claims" },
              ];
              return rings.map(ring => (
                <g key={ring.r}>
                  <circle
                    cx={ego.x}
                    cy={ego.y}
                    r={ring.r}
                    fill="none"
                    stroke={stroke}
                    strokeDasharray="3 6"
                    strokeWidth={1}
                  />
                  <text
                    x={ego.x + 6}
                    y={ego.y - ring.r - 6}
                    fill={labelFill}
                    fontFamily="'JetBrains Mono', monospace"
                    fontSize="10"
                    style={{ textTransform: "uppercase", letterSpacing: "0.12em" }}
                  >
                    {ring.label}
                  </text>
                </g>
              ));
            })()
          )}

          {/* Edges */}
          {links.map((l, i) => {
            const a = layout.byId.get(l.s);
            const b = layout.byId.get(l.t);
            if (!a || !b) return null;
            const isHL = hasHL && highlighted.has(l.s) && highlighted.has(l.t);
            const dim = hasHL && !isHL;
            const key = `${l.s}→${l.t}`;
            const isFlowing = flowEdges.has(key);
            // At rest, edges are barely visible (alpha 0.12) so the canvas
            // reads as a constellation, not a tangle. When a node is
            // focused, its edges flare to full and the rest fade further.
            const base = linkColor(l.kind, dim ? 0.04 : isHL ? 1 : 0.12);
            const sw = isHL ? 2.2 : isFlowing ? 2 : 0.6;
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

          {/* Nodes — render ego last so it sits on top, and the expanded
            * claim card (if any) last of all so its <foreignObject> paints
            * over every other pill. SVG has no z-index — document order is
            * paint order — so the only way to keep the open card on top is
            * to sort its <g> to the end of the list. In v2, ego is
            * suppressed entirely (center is "now," not "you"). */}
          {[...layout.state]
            .sort((a, b) => {
              const aExpanded = expandedClaimId === a.id ? 1 : 0;
              const bExpanded = expandedClaimId === b.id ? 1 : 0;
              if (aExpanded !== bExpanded) return aExpanded - bExpanded;
              return Number(nodeById.get(a.id)?.isEgo ?? false) - Number(nodeById.get(b.id)?.isEgo ?? false);
            })
            .filter(s => !v2 || !nodeById.get(s.id)?.isEgo)
            .map(s => {
              const n = nodeById.get(s.id);
              if (!n) return null;
              let hl = hasHL && highlighted.has(s.id);
              let dim = hasHL && !hl;
              // When a claim card is expanded, dim every other node so the
              // focused card has visual primacy. Suppress chat-highlight on
              // non-expanded nodes to avoid a confusing "dimmed but bright"
              // state where two different focus systems fight each other.
              if (expandedClaimId && s.id !== expandedClaimId) {
                hl = false;
                dim = true;
              }
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
                  v2={v2}
                  zoomK={cam.k}
                  expanded={expandedClaimId === s.id}
                  onClaimToggle={onClaimToggle}
                />
              );
            })}
        </g>
      </svg>
    </div>
  );
}
