// Hue mapping for entity_type (node color) and link_type (edge color).
// Entity types in M3 are free-form; known types get curated hues, the rest
// hash onto the wheel so colors stay consistent across sessions.

interface LinkStyleDef {
  label: string;
  hue: number;
  dash: string | null;
}

const KNOWN_ENTITY_HUES: Record<string, number> = {
  self: 340,
  person: 70,
  project: 220,
  concept: 150,
  reading: 300,
  decision: 18,
  place: 200,
  event: 40,
  tool: 180,
  org: 110,
  topic: 260,
};

const KNOWN_LINK_TYPES: Record<string, LinkStyleDef> = {
  references: { label: "references", hue: 220, dash: null },
  extends: { label: "extends", hue: 150, dash: null },
  contradicts: { label: "contradicts", hue: 18, dash: "4 4" },
  person_involved: { label: "person_involved", hue: 70, dash: null },
  source: { label: "source", hue: 300, dash: "1 3" },
  related: { label: "related", hue: 260, dash: "6 4" },
};

function hashHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return ((h % 360) + 360) % 360;
}

export function entityHue(type: string | undefined | null): number {
  if (!type) return 260;
  const k = type.toLowerCase();
  if (k in KNOWN_ENTITY_HUES) return KNOWN_ENTITY_HUES[k];
  return hashHue(k);
}

export function linkStyle(type: string | undefined | null): LinkStyleDef {
  if (!type) return { label: "link", hue: 260, dash: null };
  const k = type.toLowerCase();
  if (k in KNOWN_LINK_TYPES) return KNOWN_LINK_TYPES[k];
  return { label: type, hue: hashHue(k), dash: null };
}

export function entityColor(type: string | undefined | null, a = 1): string {
  return `oklch(0.72 0.14 ${entityHue(type)} / ${a})`;
}

export function linkColor(type: string | undefined | null, a = 1): string {
  return `oklch(0.72 0.16 ${linkStyle(type).hue} / ${a})`;
}

export function entityTypeLabel(type: string | undefined | null): string {
  if (!type) return "entity";
  return type.charAt(0).toUpperCase() + type.slice(1);
}

export const LEGEND_LINK_TYPES: Array<[string, LinkStyleDef]> = Object.entries(KNOWN_LINK_TYPES);
