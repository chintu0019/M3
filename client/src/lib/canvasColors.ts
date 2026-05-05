// Color helpers for the canvas. The design uses oklch with a fixed lightness +
// chroma, varying only hue — so a category map is just (key -> hue degrees).
//
// Categories don't come pre-baked from the backend; we derive them from
// ClusterNode.{type, entity_type, kind}. The map below is the source of truth
// for both color and the legend grouping.

export type Category =
  | "self"      // the query node (ego)
  | "person"
  | "project"
  | "concept"
  | "reading"
  | "decision"
  | "item"      // raw capture, no resolved entity_type
  | "other";

export const CATEGORY_HUE: Record<Category, number> = {
  self: 340,
  person: 70,
  project: 220,
  concept: 150,
  reading: 300,
  decision: 18,
  item: 260,
  other: 200,
};

export const CATEGORY_LABEL: Record<Category, string> = {
  self: "You",
  person: "People",
  project: "Projects",
  concept: "Concepts",
  reading: "Reading",
  decision: "Decisions",
  item: "Items",
  other: "Other",
};

export type LinkKind = "matched" | "hooks" | "related";

// Hue + dash pattern keyed by edge kind from the cluster API. The design's
// six link types collapse to three here because that's what the backend emits.
export const LINK_STYLE: Record<LinkKind, { hue: number; dash: string | null; label: string }> = {
  matched: { hue: 220, dash: null,    label: "matched" },
  hooks:   { hue: 70,  dash: null,    label: "hooks" },
  related: { hue: 260, dash: "6 4",   label: "related" },
};

/**
 * Map a ClusterNode's metadata to one of our display categories.
 * The cluster API returns free-form `kind` and `entity_type` strings, so we
 * normalize here in one place.
 */
export function deriveCategory(args: {
  type: "query" | "item" | "entity";
  entity_type: string | null;
  kind: string | null;
}): Category {
  if (args.type === "query") return "self";
  const tag = (args.entity_type || args.kind || "").toLowerCase();
  if (!tag) return args.type === "entity" ? "other" : "item";
  if (tag.includes("person") || tag === "people") return "person";
  if (tag.includes("project")) return "project";
  if (tag.includes("concept") || tag.includes("topic")) return "concept";
  if (tag.includes("read") || tag.includes("article") || tag.includes("paper")) return "reading";
  if (tag.includes("decision")) return "decision";
  return args.type === "entity" ? "other" : "item";
}

export function catColor(cat: Category, alpha = 1): string {
  return `oklch(0.72 0.14 ${CATEGORY_HUE[cat]} / ${alpha})`;
}

export function linkColor(kind: LinkKind, alpha = 1): string {
  return `oklch(0.72 0.16 ${LINK_STYLE[kind].hue} / ${alpha})`;
}
