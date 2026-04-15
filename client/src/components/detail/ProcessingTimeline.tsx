import { type ItemDetail } from "../../api/client";

function fmt(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleString();
}

function durationSec(fromIso: string | null, toIso: string | null): string {
  if (!fromIso || !toIso) return "--";
  const diff = (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 1000;
  if (diff < 60) return `${diff.toFixed(1)}s`;
  return `${Math.round(diff / 60)}m`;
}

export default function ProcessingTimeline({ item }: { item: ItemDetail }) {
  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-m3-muted mb-3">Processing Timeline</div>
      <div className="text-sm space-y-2">
        <Row label="Uploaded" value={fmt(item.created_at)} />
        <Row
          label="Started processing"
          value={fmt(item.processing_started_at)}
          extra={item.processing_started_at ? `queued ${durationSec(item.created_at, item.processing_started_at)}` : undefined}
        />
        <Row
          label={item.status === "error" ? "Failed" : "Completed"}
          value={fmt(item.processed_at)}
          extra={item.processing_started_at && item.processed_at ? `took ${durationSec(item.processing_started_at, item.processed_at)}` : undefined}
        />
      </div>
    </div>
  );
}

function Row({ label, value, extra }: { label: string; value: string; extra?: string | false | null }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-m3-muted">{label}</span>
      <span className="flex-1 text-right">
        <span>{value}</span>
        {extra && <span className="text-m3-muted ml-2">({extra})</span>}
      </span>
    </div>
  );
}
