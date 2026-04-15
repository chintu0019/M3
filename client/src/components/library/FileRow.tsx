import { Link } from "react-router-dom";
import { type RawItem } from "../../api/client";
import StatusBadge from "./StatusBadge";
import TypeIcon from "./TypeIcon";

interface FileRowProps {
  item: RawItem;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  selectMode: boolean;
}

function timeAgo(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffSec = Math.round((now - then) / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  const d = new Date(iso);
  return d.toLocaleDateString();
}

function displayName(item: RawItem): string {
  if (item.content_type === "text" && item.content_text) {
    const snip = item.content_text.slice(0, 80);
    return snip + (item.content_text.length > 80 ? "..." : "");
  }
  if (item.content_type === "url") return item.content_text || "(url)";
  return item.content_text || `[${item.content_type} file]`;
}

export default function FileRow({ item, selected, onToggleSelect, selectMode }: FileRowProps) {
  return (
    <div
      className={`group bg-m3-surface border rounded-lg p-3 flex items-center gap-3 ${
        selected ? "border-m3-accent" : "border-m3-border"
      } hover:border-m3-muted transition-colors`}
    >
      <div
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect(item.id);
        }}
        className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 cursor-pointer ${
          selected
            ? "bg-m3-accent border-m3-accent text-white"
            : "border-m3-border opacity-0 group-hover:opacity-100"
        } ${selectMode ? "opacity-100" : ""}`}
      >
        {selected && "✓"}
      </div>

      <Link to={`/library/${item.id}`} className="flex-1 min-w-0 flex items-center gap-3">
        <span className="text-lg shrink-0"><TypeIcon contentType={item.content_type} /></span>
        <div className="flex-1 min-w-0">
          <div className="text-sm truncate">{displayName(item)}</div>
          <div className="flex flex-wrap items-center gap-2 mt-0.5 text-xs text-m3-muted">
            <span>{item.content_type || "?"}</span>
            {item.user_project && <span>· {item.user_project}</span>}
            <span>· {timeAgo(item.created_at)}</span>
            {item.user_tags.length > 0 && (
              <div className="flex gap-1">
                {item.user_tags.slice(0, 3).map((t) => (
                  <span key={t} className="bg-m3-bg px-1.5 py-0.5 rounded">{t}</span>
                ))}
                {item.user_tags.length > 3 && <span>+{item.user_tags.length - 3}</span>}
              </div>
            )}
          </div>
          {item.error_message && (
            <div className="text-xs text-red-400 truncate mt-0.5">{item.error_message}</div>
          )}
        </div>
        <StatusBadge status={item.status} />
      </Link>
    </div>
  );
}
