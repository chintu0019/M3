// Collapsed claim pill — single row of SVG: rounded rect + headline text +
// confidence dot + accent left-rail. Sits at a node's (x, y) coordinate
// in canvas world-space, so the parent <g> camera transform handles zoom
// and pan automatically.

interface ClaimPillProps {
  x: number;
  y: number;
  headline: string;
  confidence: number | null;
  color: string;          // entity hue used by NodeMark
  hl: boolean;            // hard-highlighted
  dim: boolean;           // any other node is hl'd, this one fades
  onClick: () => void;
}

const PILL_HEIGHT = 22;
const PILL_PADDING_X = 10;
const PILL_FONT = 11;
const CONF_DOT_R = 3.5;
const PILL_MAX_WIDTH = 360;

// Cheap text-width estimate: 0.6em average for Inter at this size.
function estimateWidth(text: string): number {
  return Math.min(
    PILL_MAX_WIDTH,
    text.length * PILL_FONT * 0.6 + PILL_PADDING_X * 2 + CONF_DOT_R * 4,
  );
}

export function ClaimPill({
  x, y, headline, confidence, color, hl, dim, onClick,
}: ClaimPillProps) {
  const display = headline.trim() || "(no headline)";
  const width = estimateWidth(display);
  const opacity = dim ? 0.22 : 1.0;
  const stroke = hl ? color : "rgba(255, 200, 90, 0.55)";
  const fill = "oklch(0.20 0.012 260)";

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
        strokeWidth={hl ? 1.6 : 1}
      />
      {/* Accent left rail */}
      <rect
        x={2} y={4} width={2} height={PILL_HEIGHT - 8}
        rx={1} fill="rgba(255, 200, 90, 0.9)"
      />
      {/* Confidence dot */}
      {confidence != null && (
        <circle
          cx={CONF_DOT_R * 2.5}
          cy={PILL_HEIGHT / 2}
          r={CONF_DOT_R}
          fill={`oklch(0.7 0.15 ${85 + confidence * 60} / ${0.4 + confidence * 0.6})`}
        />
      )}
      <text
        x={CONF_DOT_R * 5}
        y={PILL_HEIGHT / 2 + PILL_FONT / 3}
        fill={hl ? "oklch(0.98 0.005 260)" : "oklch(0.84 0.01 260)"}
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
