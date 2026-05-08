// Single-node renderer. Two visual variants:
// - cosmos: filled disc with halo when highlighted, the ego gets concentric
//   rings + monogram letter (a la the design's pinned ego).
// - blueprint: square chip with top accent bar, ego is a double-ringed square.
//
// Lives entirely in SVG so it composes with the parent <g> camera transform
// in Graph.tsx.

import { catColor, type Category } from "../../lib/canvasColors";

export type Variant = "cosmos" | "blueprint";

export interface DisplayNode {
  id: string;
  label: string;
  cat: Category;
  isEgo: boolean;
  facts?: number;
  // Number of raw source items hooking into this entity. Surfaced as a
  // small badge so users know depth-of-evidence without rendering each item.
  sources?: number;
  excerpt?: string | null;
}

export interface NodeMarkProps {
  node: DisplayNode;
  x: number;
  y: number;
  radius: number;
  variant: Variant;
  hl: boolean;          // hard-highlighted (cited or selected)
  dim: boolean;         // any other node is highlighted, so this one fades
  pre: boolean;         // pre-highlight ring while user types
  pulse: boolean;       // pulsing right now (just got cited)
  showLabel: boolean;   // zoom is high enough to label
  showCard: boolean;    // zoom is high enough for the detail card
}

export function NodeMark({
  node, x, y, radius, variant, hl, dim, pre, pulse, showLabel, showCard,
}: NodeMarkProps) {
  const color = catColor(node.cat, 1);
  const colorDim = catColor(node.cat, 0.25);
  const fill = variant === "cosmos" ? "oklch(0.22 0.012 260)" : "oklch(0.20 0.01 260)";

  return (
    <g
      data-node={node.id}
      transform={`translate(${x}, ${y})`}
      style={{
        cursor: node.isEgo ? "default" : "grab",
        opacity: dim ? 0.22 : 1,
        transition: "opacity 220ms",
      }}
    >
      {variant === "cosmos" && (hl || pulse) && (
        <circle r={radius + 18} fill="url(#m3-node-halo)" opacity={hl ? 0.6 : 0.4} />
      )}
      {pulse && (
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
        node.isEgo ? (
          <>
            <circle r={radius + 24} fill="none" stroke={color} strokeWidth={0.8} strokeDasharray="1 4" opacity={0.55} />
            <circle r={radius + 10} fill="none" stroke={color} strokeWidth={0.6} opacity={0.4} />
            <circle r={radius} fill="oklch(0.26 0.06 340)" stroke={color} strokeWidth={1.5} filter="url(#m3-soft-glow)" />
            <text
              textAnchor="middle"
              y={6}
              fill="oklch(0.98 0.005 260)"
              fontFamily="Inter, system-ui, sans-serif"
              fontSize={radius * 0.7}
              fontWeight={600}
              style={{ pointerEvents: "none" }}
            >
              {node.label[0]?.toUpperCase() ?? "?"}
            </text>
          </>
        ) : (
          <>
            <circle r={radius} fill={fill} stroke={hl ? color : colorDim} strokeWidth={hl ? 2 : 1} filter={hl ? "url(#m3-soft-glow)" : undefined} />
            <circle r={radius * 0.4} fill={hl ? color : colorDim} />
          </>
        )
      ) : node.isEgo ? (
        <>
          <rect x={-radius} y={-radius} width={radius * 2} height={radius * 2} fill="oklch(0.24 0.05 340)" stroke={color} strokeWidth={1.4} />
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
            {node.label[0]?.toUpperCase() ?? "?"}
          </text>
        </>
      ) : (
        <>
          <rect x={-radius} y={-radius} width={radius * 2} height={radius * 2} fill={fill} stroke={hl ? color : colorDim} strokeWidth={hl ? 1.6 : 1} />
          <rect x={-radius + 3} y={-radius + 3} width={radius * 2 - 6} height={2} fill={hl ? color : colorDim} opacity={0.6} />
        </>
      )}

      {!node.isEgo && node.sources != null && node.sources > 0 && (
        <g transform={`translate(${radius * 0.85}, ${-radius * 0.85})`} style={{ pointerEvents: "none" }}>
          <circle r={9} fill="oklch(0.18 0.012 260)" stroke={color} strokeWidth={1} />
          <text
            textAnchor="middle"
            y={3.5}
            fill={color}
            fontFamily="'JetBrains Mono', monospace"
            fontSize="9.5"
            fontWeight={600}
          >
            {node.sources > 99 ? "99+" : node.sources}
          </text>
        </g>
      )}

      {showLabel && !showCard && !node.isEgo && (
        <g transform={`translate(0, ${radius + 14})`} style={{ pointerEvents: "none" }}>
          <text
            textAnchor="middle"
            fill={hl ? "oklch(0.98 0.005 260)" : "oklch(0.78 0.01 260)"}
            fontFamily="Inter, system-ui, sans-serif"
            fontSize="11"
            fontWeight={hl ? 600 : 500}
          >
            {truncate(node.label, 32)}
          </text>
        </g>
      )}
      {/* Inline detail card removed: it overlapped unreadably whenever
        * two nodes sat near each other. The right-side DetailPanel is now
        * the single source of truth for full content; clicking a node
        * opens the panel and dims everything that isn't a 1-hop neighbor. */}
    </g>
  );
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}
