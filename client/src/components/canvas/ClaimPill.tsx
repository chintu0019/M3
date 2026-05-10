// Collapsed claim pill — single row of SVG: rounded rect + headline text.
// Confidence is encoded in the border alpha (subtle), not a separate dot.
// Default stroke is neutral so claim pills don't visually conflict with
// AI-link edges (which are yellow). Highlighted state uses the entity hue.

interface ClaimPillProps {
  x: number;
  y: number;
  headline: string;
  confidence: number | null;
  color: string;          // entity hue used by NodeMark — only for highlight state
  hl: boolean;            // hard-highlighted (cited or selected)
  dim: boolean;           // any other node is hl'd, this one fades
  onClick: () => void;
}

const PILL_HEIGHT = 22;
const PILL_PADDING_X = 12;
const PILL_FONT = 11;
const PILL_MAX_WIDTH = 360;

function estimateWidth(text: string): number {
  return Math.min(
    PILL_MAX_WIDTH,
    text.length * PILL_FONT * 0.6 + PILL_PADDING_X * 2,
  );
}

export function ClaimPill({
  x, y, headline, confidence, color, hl, dim, onClick,
}: ClaimPillProps) {
  const display = headline.trim() || "(no headline)";
  const width = estimateWidth(display);
  const opacity = dim ? 0.22 : 1.0;

  // Confidence drives border alpha subtly: 0.0 conf → 0.30 alpha, 1.0 conf → 0.65.
  // Means a weakly-supported claim has a near-invisible border (visually less
  // confident-looking) without needing a separate badge.
  const conf = confidence ?? 0.6;
  const baseAlpha = 0.30 + conf * 0.35;

  // Default neutral stroke matches the canvas palette (cool blue-grey, low chroma)
  // so pills don't look like AI-link edges (which are warm yellow).
  const stroke = hl ? color : `oklch(0.55 0.02 250 / ${baseAlpha})`;
  const strokeWidth = hl ? 1.6 : 1;
  const fill = "oklch(0.18 0.012 260 / 0.95)";
  const textFill = hl ? "oklch(0.98 0.005 260)" : "oklch(0.86 0.01 260)";

  return (
    <g
      transform={`translate(${x - width / 2}, ${y - PILL_HEIGHT / 2})`}
      style={{ cursor: "pointer", opacity, transition: "opacity 220ms" }}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
    >
      <rect
        x={0} y={0} width={width} height={PILL_HEIGHT}
        rx={PILL_HEIGHT / 2} ry={PILL_HEIGHT / 2}
        fill={fill}
        stroke={stroke}
        strokeWidth={strokeWidth}
      />
      <text
        x={PILL_PADDING_X}
        y={PILL_HEIGHT / 2 + PILL_FONT / 3}
        fill={textFill}
        fontFamily="Inter, system-ui, sans-serif"
        fontSize={PILL_FONT}
        fontWeight={hl ? 600 : 500}
        style={{ userSelect: "none" }}
      >
        {display}
      </text>
    </g>
  );
}
