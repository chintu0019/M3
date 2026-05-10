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
import { recencyRadiusFor } from "./recency";
import { topicalSimilarity } from "./topical";

export interface LayoutNode {
  id: string;
  cat: Category;
  /** category neighbors of the ego sit at angleSlot * (2π / N) */
  angleSlot?: number;
  /** v2: drives topical attraction in the force layout */
  topicalVec?: number[] | null;
  /** v2: drives recency radial pull (target radius from canvas center) */
  whenIso?: string | null;
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
  /** Deterministic slot the node returns to after a drag release. Computed
   *  once at init so the radial layout reads as a clean diagram instead of
   *  the spaghetti the force-directed version produced. */
  slotX?: number;
  slotY?: number;
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

// v2 force-layout constants. Tuned for the topical+recency canvas where
// "now" is the center and similarity, not type, drives clustering.
const V2_TOPICAL_K = 0.0009;   // attraction strength scaled by similarity
const V2_RECENCY_K = 0.012;    // radial pull toward target ring
const V2_REPULSE   = 8000;     // Coulomb-style anti-overlap
const V2_DAMP      = 0.82;     // velocity damping per frame
const V2_LINK_DIST = 180;      // resting distance for link springs
const V2_LINK_BASE_K = 0.04;   // baseline spring constant
const V2_SIM_THRESHOLD = 0.55; // pairs below this similarity don't attract topically

// Deterministic angle in [0, 2π) from a node id, so v2 layout is stable
// across reloads even before forces settle.
function idAngleHash(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) | 0;
  }
  return ((h >>> 0) / 0xffffffff) * Math.PI * 2;
}

/**
 * Preferred radius from the ego per node category. Pulls each node onto a
 * concentric ring around (cx, cy) so the canvas reads as "you at the centre,
 * synthesised meaning closest, raw evidence furthest." Strong enough to
 * dominate the soft category attractor — only repulsion between nodes can
 * push a node noticeably off its ring.
 */
const RADIAL_BANDS: Partial<Record<Category, number>> = {
  self: 0,
  synthesis: 230,
  person: 380,
  project: 380,
  concept: 380,
  reading: 380,
  decision: 380,
  other: 420,
  claim: 560,
  item: 720,
};

/**
 * Preferred angular sector per category. Entities of the same kind cluster
 * angularly (people on the upper-left, projects up, concepts upper-right,
 * etc) instead of being randomly scattered around the ring. Claims and
 * items have no angular preference — they spread along their ring driven
 * only by repulsion + link forces, which keeps neighbors tight.
 */
const CATEGORY_ANGLE: Partial<Record<Category, number>> = {
  person:   Math.PI * 1.25,   // upper-left
  project:  Math.PI * 1.5,    // top
  concept:  Math.PI * 1.75,   // upper-right
  reading:  Math.PI * 0.25,   // lower-right
  decision: Math.PI * 0.5,    // bottom
  other:    Math.PI * 0.75,   // lower-left
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
  opts: { width?: number; height?: number; egoId?: string; v2?: boolean } = {},
): Layout {
  const W = opts.width ?? 1600;
  const H = opts.height ?? 1100;
  const cx = W / 2;
  const cy = H / 2;
  const egoId = opts.egoId ?? nodes.find(n => n.cat === "self")?.id;
  const v2 = !!opts.v2;

  // ── Radial slotter ──────────────────────────────────────────────────────
  // Replaces force-directed layout for the at-rest view. Each node gets a
  // deterministic slot computed in three passes:
  //   1. Ego at the centre.
  //   2. Entity nodes on the entity ring, grouped into sectors by type
  //      (people upper-left, projects up, concepts upper-right, etc).
  //   3. Synthesis nodes on the synthesis ring, each at the angle of its
  //      anchor entity. Claim nodes on the claim ring, in a tight arc near
  //      their target entity. Item nodes on the outermost ring, same logic.
  //
  // The result is "petals": every entity has its synthesis directly inside
  // it and a fan of claims directly outside. Edge lines become short radial
  // spokes instead of long diagonals.
  //
  // Drag still works: while dragging, the node follows the pointer; on
  // release it springs back to its slot.
  const angleOf = new Map<string, number>();   // node id -> radial angle around ego
  const slotXY = new Map<string, { x: number; y: number }>();

  if (v2) {
    // v2: each node gets a target radius from its when_iso (recency band)
    // and a deterministic id-hashed initial angle. Topical attraction +
    // repulsion + link springs then refine angular position over the next
    // ~500 frames.
    for (const n of nodes) {
      const r = recencyRadiusFor(n.whenIso ?? null);
      const angle = idAngleHash(n.id);
      slotXY.set(n.id, { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r });
      angleOf.set(n.id, angle);
    }
  } else {
    // Pass 1: ego.
    if (egoId) slotXY.set(egoId, { x: cx, y: cy });

    // Pass 2: entity nodes by sector. Other-typed entities (no sector) spread
    // around the unused arc on the entity ring so they don't overlap typed ones.
    const entityRing = RADIAL_BANDS.person ?? 380;
    const entitiesByCat = new Map<Category, LayoutNode[]>();
    for (const n of nodes) {
      if (n.id === egoId) continue;
      if (n.cat === "claim" || n.cat === "synthesis" || n.cat === "item") continue;
      let arr = entitiesByCat.get(n.cat);
      if (!arr) { arr = []; entitiesByCat.set(n.cat, arr); }
      arr.push(n);
    }
    for (const [cat, arr] of entitiesByCat) {
      const sectorCenter = CATEGORY_ANGLE[cat];
      if (sectorCenter != null) {
        const sectorWidth = Math.PI / 3;
        arr.forEach((n, i) => {
          const angle = arr.length === 1
            ? sectorCenter
            : sectorCenter - sectorWidth / 2 + (sectorWidth * (i + 0.5)) / arr.length;
          angleOf.set(n.id, angle);
          slotXY.set(n.id, {
            x: cx + Math.cos(angle) * (RADIAL_BANDS[cat] ?? entityRing),
            y: cy + Math.sin(angle) * (RADIAL_BANDS[cat] ?? entityRing),
          });
        });
      } else {
        // No sector: spread evenly across the full ring.
        arr.forEach((n, i) => {
          const angle = (Math.PI * 2 * (i + 0.5)) / arr.length;
          angleOf.set(n.id, angle);
          slotXY.set(n.id, {
            x: cx + Math.cos(angle) * (RADIAL_BANDS[cat] ?? entityRing),
            y: cy + Math.sin(angle) * (RADIAL_BANDS[cat] ?? entityRing),
          });
        });
      }
    }

    // Pass 3a: build a map of {claim/synthesis/item id -> primary entity id}
    // by walking the link graph.
    const primaryEntityOf = (id: string): string | null => {
      for (const l of links) {
        if (l.s === id && l.t.startsWith("entity:")) return l.t;
        if (l.t === id && l.s.startsWith("entity:")) return l.s;
      }
      return null;
    };

    // Pass 3b: synthesis nodes sit at the angle of their anchor entity, on
    // the synthesis ring. Multiple syntheses sharing one anchor jitter slightly.
    const synthsByAnchor = new Map<string | null, LayoutNode[]>();
    // Pass 3c: claim nodes sit in a tight arc at the angle of their anchor.
    const claimsByAnchor = new Map<string | null, LayoutNode[]>();
    // Pass 3d: item nodes ditto on the outermost ring.
    const itemsByAnchor = new Map<string | null, LayoutNode[]>();
    for (const n of nodes) {
      if (n.id === egoId) continue;
      if (n.cat !== "claim" && n.cat !== "synthesis" && n.cat !== "item") continue;
      const anchor = primaryEntityOf(n.id);
      const bucket =
        n.cat === "synthesis" ? synthsByAnchor :
        n.cat === "claim"     ? claimsByAnchor : itemsByAnchor;
      let arr = bucket.get(anchor);
      if (!arr) { arr = []; bucket.set(anchor, arr); }
      arr.push(n);
    }

    const placeAroundAnchor = (arr: LayoutNode[], anchorId: string | null, ring: number, arcSpread: number) => {
      // Default angle for orphaned nodes (no entity anchor): spread evenly
      // around the ring without overlapping any single entity sector.
      const baseAngle = anchorId != null ? (angleOf.get(anchorId) ?? null) : null;
      if (baseAngle == null) {
        arr.forEach((n, i) => {
          const angle = (Math.PI * 2 * (i + 0.5)) / arr.length;
          slotXY.set(n.id, { x: cx + Math.cos(angle) * ring, y: cy + Math.sin(angle) * ring });
        });
        return;
      }
      arr.forEach((n, i) => {
        const offset = arr.length === 1
          ? 0
          : ((i + 0.5) / arr.length - 0.5) * arcSpread;
        const angle = baseAngle + offset;
        slotXY.set(n.id, { x: cx + Math.cos(angle) * ring, y: cy + Math.sin(angle) * ring });
      });
    };

    for (const [anchor, arr] of synthsByAnchor) placeAroundAnchor(arr, anchor, RADIAL_BANDS.synthesis ?? 230, Math.PI / 12);
    for (const [anchor, arr] of claimsByAnchor) placeAroundAnchor(arr, anchor, RADIAL_BANDS.claim ?? 560, Math.PI / 5);
    for (const [anchor, arr] of itemsByAnchor)  placeAroundAnchor(arr, anchor, RADIAL_BANDS.item ?? 720, Math.PI / 6);
  }

  const state: LayoutState[] = nodes.map(n => {
    const isEgo = n.id === egoId;
    const pinned = !v2 && isEgo;   // v2 has no pinned ego — "now" is the center, not "you"
    const slot = slotXY.get(n.id) ?? { x: cx, y: cy };
    return {
      id: n.id, cat: n.cat,
      x: slot.x, y: slot.y, vx: 0, vy: 0,
      pinned, dragging: false, degree: 0,
      slotX: slot.x, slotY: slot.y,
    };
  });
  const byId = new Map(state.map(s => [s.id, s]));
  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  // Parallel arrays for the v2 step's hot loops — indexed by `state[i]`'s
  // position, so we avoid N^2 Map lookups per frame. Both `state` and
  // `nodes` were built in the same order via the same `nodes.map(...)` so
  // index i corresponds to the same logical node in both.
  const topicalVecs: (number[] | null | undefined)[] = nodes.map(n => n.topicalVec ?? null);
  const whenIsos: (string | null | undefined)[] = nodes.map(n => n.whenIso ?? null);

  for (const l of links) {
    const a = byId.get(l.s);
    const b = byId.get(l.t);
    if (a) a.degree++;
    if (b) b.degree++;
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

  function step() {
    if (v2) {
      stepV2();
      return;
    }
    // Drag override: dragged node tracks the pointer directly.
    if (draggingId != null && targetPos) {
      const s = byId.get(draggingId);
      if (s) {
        s.x = targetPos.x;
        s.y = targetPos.y;
        s.vx = 0; s.vy = 0;
      }
    }
    // Slot pull: every other non-pinned node lerps back toward its slot.
    // Strong enough that release-from-drag snaps within ~10 frames.
    const SLOT_K = 0.12;
    for (const s of state) {
      if (s.pinned || s.dragging) continue;
      if (s.slotX == null || s.slotY == null) continue;
      const dx = s.slotX - s.x;
      const dy = s.slotY - s.y;
      // Critically-damped spring: position += dx * SLOT_K, velocity stays near 0.
      s.x += dx * SLOT_K;
      s.y += dy * SLOT_K;
      s.vx = 0; s.vy = 0;
    }
    // Pointer is read by mouse-effect features but no longer drives layout.
    void pointer;
  }

  function stepV2() {
    // Drag override: dragged node tracks pointer
    if (draggingId != null && targetPos) {
      const s = byId.get(draggingId);
      if (s) { s.x = targetPos.x; s.y = targetPos.y; s.vx = 0; s.vy = 0; }
    }

    // 1. Recency radial pull — each non-dragged node pulled toward its target ring
    for (let i = 0; i < state.length; i++) {
      const s = state[i];
      if (s.dragging) continue;
      const target = recencyRadiusFor(whenIsos[i] ?? null);
      const dx = s.x - cx, dy = s.y - cy;
      const r = Math.hypot(dx, dy) || 1;
      const drift = (target - r) * V2_RECENCY_K;
      s.vx += (dx / r) * drift;
      s.vy += (dy / r) * drift;
    }

    // 2. Link springs — each link pulls its endpoints toward V2_LINK_DIST,
    //    scaled by topical similarity (0.4 floor + 0.6 * sim) so even unrelated
    //    linked nodes attract a bit.
    for (const l of links) {
      const a = byId.get(l.s); const b = byId.get(l.t);
      if (!a || !b) continue;
      const na = nodeMap.get(l.s); const nb = nodeMap.get(l.t);
      const sim = topicalSimilarity(na?.topicalVec ?? null, nb?.topicalVec ?? null);
      const k = V2_LINK_BASE_K * (0.4 + 0.6 * sim);
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.hypot(dx, dy) || 1;
      const f = (dist - V2_LINK_DIST) * k;
      a.vx += (dx / dist) * f; a.vy += (dy / dist) * f;
      b.vx -= (dx / dist) * f; b.vy -= (dy / dist) * f;
    }

    // Pass 3+4 fused: a single O(N^2) pair walk does Coulomb repulsion always
    // and adds topical attraction when similarity is above threshold.
    for (let i = 0; i < state.length; i++) {
      const a = state[i];
      const va = topicalVecs[i];
      for (let j = i + 1; j < state.length; j++) {
        const b = state[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d2 = Math.max(40, dx*dx + dy*dy);
        const d = Math.sqrt(d2);

        // Coulomb repulsion (always)
        const fr = V2_REPULSE / d2;
        a.vx -= (dx / d) * fr; a.vy -= (dy / d) * fr;
        b.vx += (dx / d) * fr; b.vy += (dy / d) * fr;

        // Topical attraction (only above threshold)
        const vb = topicalVecs[j];
        const sim = topicalSimilarity(va, vb);
        if (sim >= V2_SIM_THRESHOLD) {
          const fa = sim * V2_TOPICAL_K * d;
          a.vx += (dx / d) * fa; a.vy += (dy / d) * fa;
          b.vx -= (dx / d) * fa; b.vy -= (dy / d) * fa;
        }
      }
    }

    // 5. Integrate — damped Euler
    for (const s of state) {
      if (s.dragging) { s.vx = 0; s.vy = 0; continue; }
      s.vx *= V2_DAMP; s.vy *= V2_DAMP;
      s.x += s.vx; s.y += s.vy;
    }
    void pointer;
  }

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
