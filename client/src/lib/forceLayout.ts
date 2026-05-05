// Force-directed layout for the canvas. Ported from M3 Canvas.html with
// minor structural cleanup for TypeScript and to take live data instead of
// the seeded mock. Continuous physics — caller drives `step()` from a RAF
// loop so nodes breathe, drift, and respond to drag/hover.
//
// Conventions:
// - The "ego" node (cluster query) is pinned at the world center.
// - Direct neighbors of the ego sit at a fixed orbital radius, slotted by
//   index, so the ego layout reads at a glance no matter how many neighbors.
// - Non-ego nodes get a soft attraction toward their category centroid so
//   clusters form without explicit grouping.

import type { Category } from "./canvasColors";

export interface LayoutNode {
  id: string;
  cat: Category;
  /** category neighbors of the ego sit at angleSlot * (2π / N) */
  angleSlot?: number;
}

export interface LayoutLink {
  s: string;
  t: string;
}

export interface LayoutState {
  id: string;
  cat: Category;
  x: number;
  y: number;
  vx: number;
  vy: number;
  pinned: boolean;
  dragging: boolean;
  degree: number;
  angleSlot?: number;
}

export interface LayoutParams {
  repulse: number;
  linkDist: number;
  linkK: number;
  centerK: number;
  damp: number;
  catK: number;
  mouseRepel: number;
  mouseRadius: number;
  dragRepel: number;
  selfOrbit: number;
  selfOrbitK: number;
}

export const DEFAULT_PARAMS: LayoutParams = {
  repulse: 9000,
  linkDist: 180,
  linkK: 0.04,
  centerK: 0.002,
  damp: 0.82,
  catK: 0.0012,
  mouseRepel: 0,
  mouseRadius: 150,
  dragRepel: 24000,
  selfOrbit: 260,
  selfOrbitK: 0.018,
};

export interface Layout {
  state: LayoutState[];
  byId: Map<string, LayoutState>;
  width: number;
  height: number;
  step(): void;
  setMouse(x: number, y: number, active: boolean): void;
  setDrag(id: string | null, x?: number, y?: number): void;
  updateDragTarget(x: number, y: number): void;
  releaseDrag(): void;
  setParams(next: Partial<LayoutParams>): void;
}

export function initLayout(
  nodes: LayoutNode[],
  links: LayoutLink[],
  opts: { width?: number; height?: number; egoId?: string } = {},
): Layout {
  const W = opts.width ?? 1600;
  const H = opts.height ?? 1100;
  const cx = W / 2;
  const cy = H / 2;
  const egoId = opts.egoId ?? nodes.find(n => n.cat === "self")?.id;

  // Seed positions in a category-banded ring. The angles only matter for
  // initial settle — physics takes over within 500 steps.
  const cats = Array.from(new Set(nodes.map(n => n.cat)));
  const catAngle: Record<string, number> = {};
  cats.forEach((c, i) => {
    catAngle[c] = (i / cats.length) * Math.PI * 2;
  });

  const state: LayoutState[] = nodes.map((n, i) => {
    const a = catAngle[n.cat] + (i % 5) * 0.15;
    const r = n.id === egoId ? 0 : 260 + (i % 3) * 60;
    return {
      id: n.id,
      cat: n.cat,
      x: cx + Math.cos(a) * r + (Math.random() - 0.5) * 20,
      y: cy + Math.sin(a) * r + (Math.random() - 0.5) * 20,
      vx: 0,
      vy: 0,
      pinned: n.id === egoId,
      dragging: false,
      degree: 0,
    };
  });
  const byId = new Map(state.map(s => [s.id, s]));

  for (const l of links) {
    const a = byId.get(l.s);
    const b = byId.get(l.t);
    if (a) a.degree++;
    if (b) b.degree++;
  }

  if (egoId) {
    const ego = byId.get(egoId);
    if (ego) {
      ego.x = cx;
      ego.y = cy;
      ego.pinned = true;
    }
  }

  // Slot direct neighbors of ego around a fixed-radius ring so the topology is
  // legible even when forces are in motion.
  const neighbors: string[] = [];
  if (egoId) {
    const seen = new Set<string>();
    for (const l of links) {
      if (l.s === egoId && !seen.has(l.t)) { seen.add(l.t); neighbors.push(l.t); }
      else if (l.t === egoId && !seen.has(l.s)) { seen.add(l.s); neighbors.push(l.s); }
    }
    neighbors.forEach((id, i) => {
      const s = byId.get(id);
      if (!s) return;
      s.angleSlot = (i / Math.max(1, neighbors.length)) * Math.PI * 2;
      s.x = cx + Math.cos(s.angleSlot) * DEFAULT_PARAMS.selfOrbit;
      s.y = cy + Math.sin(s.angleSlot) * DEFAULT_PARAMS.selfOrbit;
    });
  }

  const params: LayoutParams = { ...DEFAULT_PARAMS };
  const pointer = { x: 0, y: 0, active: false };
  let draggingId: string | null = null;
  let targetPos: { x: number; y: number } | null = null;

  function setMouse(x: number, y: number, active: boolean) {
    pointer.x = x; pointer.y = y; pointer.active = active;
  }
  function setDrag(id: string | null, x = 0, y = 0) {
    draggingId = id;
    targetPos = id == null ? null : { x, y };
    state.forEach(s => { s.dragging = s.id === id; });
  }
  function updateDragTarget(x: number, y: number) {
    if (targetPos) { targetPos.x = x; targetPos.y = y; }
  }
  function releaseDrag() {
    draggingId = null;
    targetPos = null;
    state.forEach(s => { s.dragging = false; });
  }

  function catCenters() {
    const m = new Map<string, { x: number; y: number; n: number }>();
    for (const s of state) {
      let c = m.get(s.cat);
      if (!c) { c = { x: 0, y: 0, n: 0 }; m.set(s.cat, c); }
      c.x += s.x; c.y += s.y; c.n++;
    }
    for (const c of m.values()) { c.x /= c.n; c.y /= c.n; }
    return m;
  }

  function step() {
    // Pairwise repulsion (O(n²) — fine for the tens-to-hundreds of nodes
    // a single user's brain produces; no Barnes-Hut needed at this scale).
    for (let i = 0; i < state.length; i++) {
      const a = state[i];
      for (let j = i + 1; j < state.length; j++) {
        const b = state[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { d2 = 1; dx = 1; dy = 0; }
        const repel = a.dragging || b.dragging ? params.dragRepel : params.repulse;
        const f = repel / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }
    // Spring along links
    for (const l of links) {
      const a = byId.get(l.s);
      const b = byId.get(l.t);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const diff = d - params.linkDist;
      const fx = (dx / d) * diff * params.linkK;
      const fy = (dy / d) * diff * params.linkK;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
    // Soft pull toward category centroid
    const centers = catCenters();
    for (const s of state) {
      const c = centers.get(s.cat);
      if (!c) continue;
      s.vx += (c.x - s.x) * params.catK;
      s.vy += (c.y - s.y) * params.catK;
    }
    // Ego ring force
    if (neighbors.length > 0) {
      for (const id of neighbors) {
        const s = byId.get(id);
        if (!s || s.dragging || s.pinned) continue;
        const tx = cx + Math.cos(s.angleSlot ?? 0) * params.selfOrbit;
        const ty = cy + Math.sin(s.angleSlot ?? 0) * params.selfOrbit;
        s.vx += (tx - s.x) * params.selfOrbitK;
        s.vy += (ty - s.y) * params.selfOrbitK;
      }
    }
    // Center pull
    for (const s of state) {
      s.vx += (cx - s.x) * params.centerK;
      s.vy += (cy - s.y) * params.centerK;
    }
    // Mouse repel (off by default — was fighting the user when they tried to
    // grab a node; left in so it can be toggled via tweaks)
    if (pointer.active && params.mouseRepel > 0) {
      const R = params.mouseRadius, R2 = R * R;
      for (const s of state) {
        if (s.dragging) continue;
        const dx = s.x - pointer.x, dy = s.y - pointer.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < R2 && d2 > 0.01) {
          const d = Math.sqrt(d2);
          const falloff = 1 - d / R;
          const f = (params.mouseRepel * falloff * falloff) / d2;
          s.vx += (dx / d) * f;
          s.vy += (dy / d) * f;
        }
      }
    }
    // Drag override
    if (draggingId != null && targetPos) {
      const s = byId.get(draggingId);
      if (s) {
        s.vx = (targetPos.x - s.x) * 0.6;
        s.vy = (targetPos.y - s.y) * 0.6;
      }
    }
    // Integrate
    for (const s of state) {
      if (s.pinned) { s.vx = 0; s.vy = 0; continue; }
      if (s.dragging) { s.x += s.vx; s.y += s.vy; continue; }
      s.vx *= params.damp; s.vy *= params.damp;
      s.x += s.vx; s.y += s.vy;
    }
  }

  // Pre-settle so initial render is stable, not a flying-around spaghetti
  // that resolves over a second.
  for (let i = 0; i < 500; i++) step();

  return {
    state,
    byId,
    width: W,
    height: H,
    step,
    setMouse,
    setDrag,
    updateDragTarget,
    releaseDrag,
    setParams(next) { Object.assign(params, next); },
  };
}
