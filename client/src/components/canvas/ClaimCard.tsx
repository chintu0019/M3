// Expanded claim card — uses SVG <foreignObject> so the HTML content
// inherits the canvas camera transform (zoom + pan) automatically,
// while still letting us use real HTML/CSS for the multi-line layout
// the SVG <text> element makes painful.

interface ClaimCardProps {
  x: number;
  y: number;
  headline: string;
  proposition: string;
  confidence: number | null;
  sourceCount: number;
  whenIso: string | null;
  onDismiss: () => void;
}

const CARD_WIDTH = 320;
const CARD_HEIGHT = 180;

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function ClaimCard({
  x, y, headline, proposition, confidence, sourceCount, whenIso, onDismiss,
}: ClaimCardProps) {
  const dateLabel = formatDate(whenIso);
  return (
    <foreignObject
      x={x - CARD_WIDTH / 2}
      y={y + 18}
      width={CARD_WIDTH}
      height={CARD_HEIGHT}
      style={{ overflow: "visible" }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        // xmlns set via spread to bypass React's HTML typings (xmlns is required
        // by SVG spec inside <foreignObject> so the inner tree is parsed as XHTML)
        {...{ xmlns: "http://www.w3.org/1999/xhtml" }}
        style={{
          background: "oklch(0.16 0.012 260)",
          border: "1px solid oklch(0.45 0.05 80 / 0.8)",
          borderRadius: 8,
          padding: "10px 12px",
          color: "oklch(0.93 0.005 260)",
          fontFamily: "Inter, system-ui, sans-serif",
          boxShadow: "0 4px 24px rgba(0, 0, 0, 0.5)",
        }}
      >
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 9, letterSpacing: "0.12em",
          color: "rgba(255, 200, 90, 0.95)",
          textTransform: "uppercase", display: "flex", alignItems: "center", gap: 6,
        }}>
          <span>CLAIM</span>
          <span style={{ opacity: 0.5 }}>·</span>
          <span style={{ color: "oklch(0.93 0.005 260)" }}>{headline}</span>
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(); }}
            style={{
              marginLeft: "auto", background: "transparent", border: 0,
              color: "rgba(255, 255, 255, 0.5)", cursor: "pointer", fontSize: 14,
              lineHeight: 1, padding: 0,
            }}
            aria-label="Close claim card"
          >
            ×
          </button>
        </div>
        <div style={{
          fontSize: 13, lineHeight: 1.45, marginTop: 8, fontWeight: 500,
        }}>
          {proposition}
        </div>
        <div style={{
          marginTop: 8, paddingTop: 6, borderTop: "1px solid oklch(0.22 0.012 260)",
          display: "flex", alignItems: "center", gap: 10,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 9.5,
          color: "oklch(0.62 0.01 260)", letterSpacing: "0.04em",
        }}>
          {sourceCount > 0 && (
            <span style={{
              background: "oklch(0.20 0.012 260)",
              border: "1px solid oklch(0.28 0.012 260)",
              borderRadius: 9999, padding: "1px 6px",
              color: "oklch(0.78 0.01 260)",
            }}>
              {sourceCount} {sourceCount === 1 ? "source" : "sources"}
            </span>
          )}
          {confidence != null && <span>conf {confidence.toFixed(2)}</span>}
          {dateLabel && <span>{dateLabel}</span>}
        </div>
      </div>
    </foreignObject>
  );
}
