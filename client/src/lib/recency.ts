// Bucket a chat by its updated_at relative to "now" (default Date.now()).
// Mirrors the visual sections in the sidebar, the only consumer.

export type RecencyBucket =
  | "today"
  | "yesterday"
  | "previous7"
  | "previous30"
  | "older";

export const BUCKET_LABEL: Record<RecencyBucket, string> = {
  today: "Today",
  yesterday: "Yesterday",
  previous7: "Previous 7 Days",
  previous30: "Previous 30 Days",
  older: "Older",
};

export const BUCKET_ORDER: RecencyBucket[] = [
  "today",
  "yesterday",
  "previous7",
  "previous30",
  "older",
];

export function bucketFor(iso: string, now: Date = new Date()): RecencyBucket {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "older";
  const day = 86_400_000;
  const startOfToday = new Date(
    now.getFullYear(), now.getMonth(), now.getDate(),
  ).getTime();
  const diff = startOfToday - ts;
  if (ts >= startOfToday) return "today";
  if (ts >= startOfToday - day) return "yesterday";
  if (diff < 7 * day) return "previous7";
  if (diff < 30 * day) return "previous30";
  return "older";
}

// =============================================================================
// Canvas v2 recency bands
// =============================================================================
//
// Different concept than the RecencyBucket above (which is used by the chat
// sidebar). These bands map a `when_iso` to a target radius from canvas
// center. The center is "now"; older nodes drift outward through four nested
// rings. Used by the canvas v2 force layout (lib/forceLayout.ts) and the
// recency-ring guides drawn in components/canvas/Graph.tsx.

export type RecencyBand = "week" | "month" | "quarter" | "earlier" | "unknown";

export const RECENCY_RING_RADII: Record<RecencyBand, number> = {
  week:    140,
  month:   260,
  quarter: 420,
  earlier: 600,
  unknown: 600,   // unknown dates park out at the edge with the oldest stuff
};

export const RECENCY_RING_LABELS: Record<Exclude<RecencyBand, "unknown">, string> = {
  week:    "THIS WEEK",
  month:   "THIS MONTH",
  quarter: "THIS QUARTER",
  earlier: "EARLIER",
};

const DAY = 24 * 3600 * 1000;

export function recencyBandFor(whenIso: string | null | undefined, now: Date = new Date()): RecencyBand {
  if (!whenIso) return "unknown";
  const t = Date.parse(whenIso);
  if (Number.isNaN(t)) return "unknown";
  const ageDays = (now.getTime() - t) / DAY;
  if (ageDays <= 7)   return "week";
  if (ageDays <= 31)  return "month";
  if (ageDays <= 92)  return "quarter";
  return "earlier";
}

export function recencyRadiusFor(whenIso: string | null | undefined, now: Date = new Date()): number {
  return RECENCY_RING_RADII[recencyBandFor(whenIso, now)];
}

export function recencyOpacityFor(whenIso: string | null | undefined, now: Date = new Date()): number {
  // Older nodes render dimmer; this is the always-on time signal on canvas v2.
  // 1.0 (week) → 0.85 (month) → 0.65 (quarter) → 0.45 (earlier/unknown).
  switch (recencyBandFor(whenIso, now)) {
    case "week":    return 1.0;
    case "month":   return 0.85;
    case "quarter": return 0.65;
    case "earlier":
    case "unknown":
    default:        return 0.45;
  }
}

// Dev sanity checks — only run during `vite dev`, never in production builds.
if (import.meta.env.DEV) {
  const _now = new Date("2026-05-10T12:00:00Z");
  console.assert(recencyBandFor("2026-05-08T10:00:00Z", _now) === "week", "week band");
  console.assert(recencyBandFor("2026-04-20T10:00:00Z", _now) === "month", "month band");
  console.assert(recencyBandFor("2026-03-15T10:00:00Z", _now) === "quarter", "quarter band");
  console.assert(recencyBandFor("2025-10-15T10:00:00Z", _now) === "earlier", "earlier band");
  console.assert(recencyBandFor(null, _now) === "unknown", "unknown band");
  console.assert(recencyRadiusFor("2026-05-08T10:00:00Z", _now) === 140, "week radius");
  console.assert(recencyRadiusFor(null, _now) === 600, "unknown → outer radius");
  console.assert(recencyOpacityFor("2026-05-08T10:00:00Z", _now) === 1.0, "week opacity");
  console.assert(recencyOpacityFor(null, _now) === 0.45, "unknown opacity");
}
