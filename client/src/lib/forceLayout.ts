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
const V2_REPULSE   = 18000;    // Coulomb-style anti-overlap
const V2_DAMP      = 0.55;     // velocity damping per frame — lower than 0.82
                                //   so equilibrium velocity collapses faster
const V2_MAX_V     = 4;        // hard per-frame velocity cap so a freshly-cooled
                                //   layout can't sling a node across the canvas
const V2_LINK_DIST = 180;      // resting distance for link springs
const V2_LINK_BASE_K = 0.04;   // baseline spring constant
const V2_SIM_THRESHOLD = 0.55; // pairs below this similarity don't attract topically

// Cooling schedule. Forces never zero out (recency + topical pulls are always
// active), so without a temperature term the system settles to a non-zero
// equilibrium velocity and jitters forever. Multiplying every force by a
// temperature that decays from 1.0 to V2_COOL_FLOOR over ~10s gives an early
// "find your spot" phase followed by a near-static at-rest canvas.
const V2_COOL_FRAMES = 600;    // ~10s at 60Hz
const V2_COOL_FLOOR  = 0.05;   // residual breathing once cool
const V2_REHEAT_ON_DRAG = 200; // frames of warmth restored when a drag starts

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

/**
 * Position snapshot used to preserve continuity when `initLayout` is rebuilt
 * with the same node identities (e.g. when an entity is expanded so a few
 * claim/item nodes appear, but the entity ring itself shouldn't snap back to
 * id-hash slots). Caller captures this from the previous layout's `state`.
 */
export type PrevPositions = Map<string, { x: number; y: number; vx: number; vy: number }>;

export function initLayout(
  nodes: LayoutNode[],
  links: LayoutLink[],
  opts: {
    width?: number;
    height?: number;
    egoId?: string;
    v2?: boolean;
    /** Reuse position+velocity for matching ids so a layout rebuild driven
     *  by a click (e.g. expanding an entity) doesn't reset every node to its
     *  initial slot. Initial frame counter is set to "mostly cool" when this
     *  is non-empty, so new nodes get a brief settle without the full 10s
     *  warm-up reshuffling everyone. */
    prev?: PrevPositions;
  } = {},
): Layout {
  const W = opts.width ?? 1600;
  const H = opts.height ?? 1100;
  const cx = W / 2;
  const cy = H / 2;
  const egoId = opts.egoId ?? nodes.find(n => n.cat === "self")?.id;
  const v2 = !!opts.v2;
  const prev = opts.prev;

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
    // and a deterministic even-spread initial angle. Topical attraction +
    // repulsion + link springs then refine angular position over the next
    // ~500 frames.
    //
    // Sort node IDs and slot them evenly around the circle so the initial
    // layout has uniform angular distribution regardless of ID string biases
    // (claim:<uuid>, entity:<slug> etc share prefixes that pollute hashes).
    const sortedIds = [...nodes].map(n => n.id).sort();
    const angleByid = new Map<string, number>();
    for (let i = 0; i < sortedIds.length; i++) {
      angleByid.set(sortedIds[i], (i / sortedIds.length) * Math.PI * 2);
    }
    for (const n of nodes) {
      const r = recencyRadiusFor(n.whenIso ?? null);
      const angle = angleByid.get(n.id) ?? 0;
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
    // If we have a previous position for this id, reuse it. The slot is still
    // computed (so it can serve as a fall-back / drag-release target on v1),
    // but `x/y/vx/vy` carry over so the node visibly stays where the user
    // left it across rebuilds.
    const carry = prev?.get(n.id);
    return {
      id: n.id, cat: n.cat,
      x: carry?.x ?? slot.x,
      y: carry?.y ?? slot.y,
      vx: carry?.vx ?? 0,
      vy: carry?.vy ?? 0,
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

  // Frame counter for the v2 cooling schedule. Starts hot (frame=0) so the
  // initial id-hash angles get pulled into clusters, then cools. When we
  // re-init with carried-over positions (typical click → reveal claims path)
  // jump straight to "mostly cool" — most nodes are already settled, we only
  // need a brief warm phase for the new arrivals.
  let frame = prev && prev.size > 0 ? Math.floor(V2_COOL_FRAMES * 0.7) : 0;
  function temperature(): number {
    const t = Math.min(1, frame / V2_COOL_FRAMES);
    // Quadratic ease-out from 1.0 toward V2_COOL_FLOOR.
    return V2_COOL_FLOOR + (1 - V2_COOL_FLOOR) * (1 - t) * (1 - t);
  }

  function setMouse(x: number, y: number, active: boolean) {
    pointer.x = x; pointer.y = y; pointer.active = active;
  }
  function setDrag(id: string | null, x = 0, y = 0) {
    draggingId = id;
    targetPos = id == null ? null : { x, y };
    state.forEach(s => { s.dragging = s.id === id; });
    // Reheat: a drag should let neighbors react meaningfully instead of
    // creeping at the cooled-floor velocity.
    if (id != null && v2) frame = Math.max(0, frame - V2_REHEAT_ON_DRAG);
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

    // Cooling: every force contribution is multiplied by `temp`. Early frames
    // run at full strength; once cool the canvas barely breathes.
    const temp = temperature();

    // 1. Recency radial pull — each non-dragged node pulled toward its target ring.
    //    NOT subject to cooling: the recency band is a structural property of the
    //    node, not an animated force, so it always pulls at full strength. Without
    //    this, once the system cools nodes lose their radial anchor and topical
    //    attraction drags them into clumps.
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
      const k = V2_LINK_BASE_K * (0.4 + 0.6 * sim) * temp;
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
        // Floor bumped to 100 to soften close-range force spikes that caused
        // the "jumping" feel between wide pill nodes.
        const d2 = Math.max(100, dx*dx + dy*dy);
        const d = Math.sqrt(d2);

        // Coulomb repulsion (always)
        const fr = (V2_REPULSE / d2) * temp;
        a.vx -= (dx / d) * fr; a.vy -= (dy / d) * fr;
        b.vx += (dx / d) * fr; b.vy += (dy / d) * fr;

        // Topical attraction (only above threshold) — tangential to each
        // node's recency ring. Two topically-similar nodes on different
        // bands shift along their OWN rings toward each other angularly
        // rather than dragging each other radially across rings. Recency
        // owns the radial axis; topical owns the angular axis.
        const vb = topicalVecs[j];
        const sim = topicalSimilarity(va, vb);
        if (sim >= V2_SIM_THRESHOLD) {
          const fa = sim * V2_TOPICAL_K * Math.min(d, 200) * temp;
          // Direction from a to b (a should move toward b, b toward a)
          const ux = dx / d;
          const uy = dy / d;
          // Tangent at A: perpendicular to radial direction (a - center)
          const radAx = a.x - cx;
          const radAy = a.y - cy;
          const radAlen = Math.hypot(radAx, radAy) || 1;
          const tanAx = -radAy / radAlen;
          const tanAy = radAx / radAlen;
          // Tangent at B
          const radBx = b.x - cx;
          const radBy = b.y - cy;
          const radBlen = Math.hypot(radBx, radBy) || 1;
          const tanBx = -radBy / radBlen;
          const tanBy = radBx / radBlen;
          // Project (ux, uy) onto each tangent (signed magnitude)
          const projA = ux * tanAx + uy * tanAy;
          const projB = ux * tanBx + uy * tanBy;
          a.vx += tanAx * projA * fa;
          a.vy += tanAy * projA * fa;
          b.vx -= tanBx * projB * fa;
          b.vy -= tanBy * projB * fa;
        }
      }
    }

    // 5. Integrate — damped Euler with a hard per-frame velocity cap. Without
    //    the cap a freshly-reheated drag can fling neighbors hundreds of pixels
    //    in a single tick; the cap also bounds drift if cooling ever fails.
    //    Once cool, velocity is hard-zeroed every frame for non-dragged nodes,
    //    eliminating perpetual micro-drift after settling.
    const cool = temp < 0.1;
    for (const s of state) {
      if (s.dragging) { s.vx = 0; s.vy = 0; continue; }
      s.vx *= V2_DAMP; s.vy *= V2_DAMP;
      if (s.vx >  V2_MAX_V) s.vx =  V2_MAX_V;
      else if (s.vx < -V2_MAX_V) s.vx = -V2_MAX_V;
      if (s.vy >  V2_MAX_V) s.vy =  V2_MAX_V;
      else if (s.vy < -V2_MAX_V) s.vy = -V2_MAX_V;
      s.x += s.vx; s.y += s.vy;
      if (cool) { s.vx = 0; s.vy = 0; }
    }
    frame++;
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
