// Force-directed layout with drag, hover repulsion, and optional ego-orbit.
// Adapted from the M3 Canvas design prototype for use against live backend data.

export interface PhysicsNode {
  id: string;
  cat: string;
  pinned: boolean;
}

export interface PhysicsLink {
  s: string;
  t: string;
}

export interface PhysicsState {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  pinned: boolean;
  dragging: boolean;
  cat: string;
  degree: number;
  angleSlot?: number;
}

export interface PhysicsParams {
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

export interface PhysicsSim {
  state: PhysicsState[];
  byId: Map<string, PhysicsState>;
  width: number;
  height: number;
  step(): void;
  setMouse(x: number, y: number, active: boolean): void;
  setDrag(id: string | null, x: number, y: number): void;
  updateDragTarget(x: number, y: number): void;
  releaseDrag(): void;
  setParams(next: Partial<PhysicsParams>): void;
  hasNode(id: string): boolean;
}

export interface InitOptions {
  width?: number;
  height?: number;
  egoId?: string | null;
}

export function initSim(
  nodes: PhysicsNode[],
  links: PhysicsLink[],
  opts: InitOptions = {},
): PhysicsSim {
  const W = opts.width ?? 1600;
  const H = opts.height ?? 1100;
  const cx = W / 2,
    cy = H / 2;
  const egoId = opts.egoId ?? null;

  const cats = Array.from(new Set(nodes.map((n) => n.cat)));
  const catAngles: Record<string, number> = {};
  cats.forEach((c, i) => {
    catAngles[c] = (i / Math.max(1, cats.length)) * Math.PI * 2;
  });

  const state: PhysicsState[] = nodes.map((n, i) => {
    const a = (catAngles[n.cat] ?? 0) + (i % 5) * 0.15;
    const r = n.id === egoId ? 0 : 260 + (i % 3) * 60;
    return {
      id: n.id,
      x: cx + Math.cos(a) * r + (Math.random() - 0.5) * 20,
      y: cy + Math.sin(a) * r + (Math.random() - 0.5) * 20,
      vx: 0,
      vy: 0,
      pinned: n.pinned || n.id === egoId,
      dragging: false,
      cat: n.cat,
      degree: 0,
    };
  });
  const byId = new Map(state.map((s) => [s.id, s]));

  links.forEach((l) => {
    const a = byId.get(l.s),
      b = byId.get(l.t);
    if (a) a.degree++;
    if (b) b.degree++;
  });

  const ego = egoId ? byId.get(egoId) : null;
  if (ego) {
    ego.x = cx;
    ego.y = cy;
    ego.pinned = true;
  }

  const egoNeighbors = new Set<string>();
  if (egoId) {
    links.forEach((l) => {
      if (l.s === egoId) egoNeighbors.add(l.t);
      else if (l.t === egoId) egoNeighbors.add(l.s);
    });
  }
  const neighList = Array.from(egoNeighbors);
  neighList.forEach((id, i) => {
    const s = byId.get(id);
    if (!s) return;
    s.angleSlot = (i / neighList.length) * Math.PI * 2;
    s.x = cx + Math.cos(s.angleSlot) * 260;
    s.y = cy + Math.sin(s.angleSlot) * 260;
  });

  const params: PhysicsParams = {
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

  const pointer = { x: 0, y: 0, active: false };
  let draggingId: string | null = null;
  let targetPos: { x: number; y: number } | null = null;

  function catCenters() {
    const m = new Map<string, { x: number; y: number; n: number }>();
    state.forEach((s) => {
      if (!m.has(s.cat)) m.set(s.cat, { x: 0, y: 0, n: 0 });
      const c = m.get(s.cat)!;
      c.x += s.x;
      c.y += s.y;
      c.n++;
    });
    for (const c of m.values()) {
      c.x /= c.n;
      c.y /= c.n;
    }
    return m;
  }

  function step() {
    for (let i = 0; i < state.length; i++) {
      const a = state[i];
      for (let j = i + 1; j < state.length; j++) {
        const b = state[j];
        let dx = a.x - b.x,
          dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          d2 = 1;
          dx = 1;
          dy = 0;
        }
        const repel = a.dragging || b.dragging ? params.dragRepel : params.repulse;
        const f = repel / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f,
          fy = (dy / d) * f;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }
    links.forEach((l) => {
      const a = byId.get(l.s),
        b = byId.get(l.t);
      if (!a || !b) return;
      const dx = b.x - a.x,
        dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const diff = d - params.linkDist;
      const fx = (dx / d) * diff * params.linkK;
      const fy = (dy / d) * diff * params.linkK;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    });
    const centers = catCenters();
    state.forEach((s) => {
      const c = centers.get(s.cat);
      if (!c) return;
      s.vx += (c.x - s.x) * params.catK;
      s.vy += (c.y - s.y) * params.catK;
    });
    neighList.forEach((id) => {
      const s = byId.get(id);
      if (!s || s.dragging || s.pinned || s.angleSlot === undefined) return;
      const tx = cx + Math.cos(s.angleSlot) * params.selfOrbit;
      const ty = cy + Math.sin(s.angleSlot) * params.selfOrbit;
      s.vx += (tx - s.x) * params.selfOrbitK;
      s.vy += (ty - s.y) * params.selfOrbitK;
    });
    state.forEach((s) => {
      s.vx += (cx - s.x) * params.centerK;
      s.vy += (cy - s.y) * params.centerK;
    });
    if (pointer.active) {
      const R = params.mouseRadius,
        R2 = R * R;
      state.forEach((s) => {
        if (s.dragging) return;
        const dx = s.x - pointer.x,
          dy = s.y - pointer.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < R2 && d2 > 0.01) {
          const d = Math.sqrt(d2);
          const falloff = 1 - d / R;
          const f = (params.mouseRepel * falloff * falloff) / d2;
          s.vx += (dx / d) * f;
          s.vy += (dy / d) * f;
        }
      });
    }
    if (draggingId != null && targetPos) {
      const s = byId.get(draggingId);
      if (s) {
        s.vx = (targetPos.x - s.x) * 0.6;
        s.vy = (targetPos.y - s.y) * 0.6;
      }
    }
    state.forEach((s) => {
      if (s.pinned) {
        s.vx = 0;
        s.vy = 0;
        return;
      }
      if (s.dragging) {
        s.x += s.vx;
        s.y += s.vy;
        return;
      }
      s.vx *= params.damp;
      s.vy *= params.damp;
      s.x += s.vx;
      s.y += s.vy;
    });
  }

  // Pre-settle so the initial view isn't chaotic.
  for (let i = 0; i < 500; i++) step();

  return {
    state,
    byId,
    width: W,
    height: H,
    step,
    setMouse(x, y, active) {
      pointer.x = x;
      pointer.y = y;
      pointer.active = active;
    },
    setDrag(id, x, y) {
      draggingId = id;
      targetPos = id == null ? null : { x, y };
      state.forEach((s) => {
        s.dragging = s.id === id;
      });
    },
    updateDragTarget(x, y) {
      if (targetPos) {
        targetPos.x = x;
        targetPos.y = y;
      }
    },
    releaseDrag() {
      draggingId = null;
      targetPos = null;
      state.forEach((s) => {
        s.dragging = false;
      });
    },
    setParams(next) {
      Object.assign(params, next);
    },
    hasNode(id) {
      return byId.has(id);
    },
  };
}
