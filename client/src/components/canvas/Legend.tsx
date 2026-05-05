// Bottom-right legend showing every link kind currently in the cluster, with
// its color and dash style. Hidden if the graph has no edges.

import { LINK_STYLE, linkColor, type LinkKind } from "../../lib/canvasColors";

export interface LegendProps {
  kinds: LinkKind[];
}

export function Legend({ kinds }: LegendProps) {
  if (kinds.length === 0) return null;
  return (
    <div className="m3-legend">
      <div className="m3-legend__title">LINKS</div>
      {kinds.map(k => (
        <div key={k} className="m3-legend__row">
          <svg width="28" height="8">
            <line
              x1="0"
              y1="4"
              x2="28"
              y2="4"
              stroke={linkColor(k, 0.95)}
              strokeWidth="1.5"
              strokeDasharray={LINK_STYLE[k].dash || undefined}
            />
          </svg>
          <span className="m3-legend__label">{LINK_STYLE[k].label}</span>
        </div>
      ))}
    </div>
  );
}
