import type { PhysicsSim } from "./graphPhysics";
import type { CameraRef } from "./GraphCanvas";
import { entityColor, LEGEND_LINK_TYPES, linkColor } from "./graphStyle";

export interface GraphMinimapProps {
  sim: PhysicsSim;
  camera: CameraRef;
  viewSize: { w: number; h: number };
  highlighted: Set<string>;
  nodeCat: (id: string) => string;
}

export function GraphMinimap({ sim, camera, viewSize, highlighted, nodeCat }: GraphMinimapProps) {
  const MW = 180,
    MH = 120;
  const pad = 40;
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  sim.state.forEach((s) => {
    if (s.x < minX) minX = s.x;
    if (s.y < minY) minY = s.y;
    if (s.x > maxX) maxX = s.x;
    if (s.y > maxY) maxY = s.y;
  });
  if (!isFinite(minX)) {
    minX = 0;
    minY = 0;
    maxX = 1;
    maxY = 1;
  }
  minX -= pad;
  minY -= pad;
  maxX += pad;
  maxY += pad;
  const w = maxX - minX,
    h = maxY - minY;
  const scale = Math.min(MW / w, MH / h);

  const toMini = (x: number, y: number): [number, number] => [
    (x - minX) * scale,
    (y - minY) * scale,
  ];

  const vx1 = -camera.x / camera.k;
  const vy1 = -camera.y / camera.k;
  const vx2 = vx1 + viewSize.w / camera.k;
  const vy2 = vy1 + viewSize.h / camera.k;
  const [rx1, ry1] = toMini(vx1, vy1);
  const [rx2, ry2] = toMini(vx2, vy2);

  const cats = new Map<string, typeof sim.state>();
  sim.state.forEach((s) => {
    if (!cats.has(s.cat)) cats.set(s.cat, []);
    cats.get(s.cat)!.push(s);
  });

  return (
    <div className="m3-minimap">
      <div className="m3-minimap__label">MAP</div>
      <svg width={MW} height={MH} style={{ display: "block" }}>
        {Array.from(cats.entries()).map(([cat, ns]) => {
          if (!ns.length) return null;
          let cx = 0,
            cy = 0;
          ns.forEach((n) => {
            cx += n.x;
            cy += n.y;
          });
          cx /= ns.length;
          cy /= ns.length;
          let r = 0;
          ns.forEach((n) => {
            r = Math.max(r, Math.hypot(n.x - cx, n.y - cy));
          });
          const [mx, my] = toMini(cx, cy);
          return (
            <circle
              key={cat}
              cx={mx}
              cy={my}
              r={(r + 40) * scale}
              fill={entityColor(cat, 0.06)}
              stroke={entityColor(cat, 0.3)}
              strokeWidth={0.6}
            />
          );
        })}
        {sim.state.map((n) => {
          const [x, y] = toMini(n.x, n.y);
          const hl = highlighted && highlighted.has(n.id);
          return (
            <circle
              key={n.id}
              cx={x}
              cy={y}
              r={hl ? 3 : 1.5}
              fill={hl ? entityColor(nodeCat(n.id)) : entityColor(nodeCat(n.id), 0.6)}
            />
          );
        })}
        <rect
          x={rx1}
          y={ry1}
          width={Math.max(0, rx2 - rx1)}
          height={Math.max(0, ry2 - ry1)}
          fill="none"
          stroke="oklch(0.96 0.005 260 / 0.6)"
          strokeWidth={1}
        />
      </svg>
    </div>
  );
}

export function GraphLegend() {
  return (
    <div className="m3-legend">
      <div className="m3-legend__title">LINKS</div>
      {LEGEND_LINK_TYPES.map(([k, v]) => (
        <div key={k} className="m3-legend__row">
          <svg width="28" height="8">
            <line
              x1="0"
              y1="4"
              x2="28"
              y2="4"
              stroke={linkColor(k, 0.95)}
              strokeWidth={1.5}
              strokeDasharray={v.dash || undefined}
            />
          </svg>
          <span>{v.label}</span>
        </div>
      ))}
    </div>
  );
}
