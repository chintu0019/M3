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
