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
  opts: { width?: number; height?: number; egoId?: string } = {},
): Layout {
  const W = opts.width ?? 1600;
  const H = opts.height ?? 1100;
  const cx = W / 2;
  const cy = H / 2;
  const egoId = opts.egoId ?? nodes.find(n => n.cat === "self")?.id;

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
  function primaryEntityOf(id: string): string | null {
    for (const l of links) {
      if (l.s === id && l.t.startsWith("entity:")) return l.t;
      if (l.t === id && l.s.startsWith("entity:")) return l.s;
    }
    return null;
  }

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

  function placeAroundAnchor(arr: LayoutNode[], anchorId: string | null, ring: number, arcSpread: number) {
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
  }

  for (const [anchor, arr] of synthsByAnchor) placeAroundAnchor(arr, anchor, RADIAL_BANDS.synthesis ?? 230, Math.PI / 12);
  for (const [anchor, arr] of claimsByAnchor) placeAroundAnchor(arr, anchor, RADIAL_BANDS.claim ?? 560, Math.PI / 5);
  for (const [anchor, arr] of itemsByAnchor)  placeAroundAnchor(arr, anchor, RADIAL_BANDS.item ?? 720, Math.PI / 6);

  const state: LayoutState[] = nodes.map(n => {
    const isEgo = n.id === egoId;
    const slot = slotXY.get(n.id) ?? { x: cx, y: cy };
    return {
      id: n.id, cat: n.cat,
      x: slot.x, y: slot.y, vx: 0, vy: 0,
      pinned: isEgo, dragging: false, degree: 0,
      slotX: slot.x, slotY: slot.y,
    };
  });
  const byId = new Map(state.map(s => [s.id, s]));

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
