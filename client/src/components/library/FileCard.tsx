import { Link } from "react-router-dom";
import { type RawItem } from "../../api/client";
import StatusBadge from "./StatusBadge";
import TypeIcon from "./TypeIcon";

interface Props {
  item: RawItem;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  selectMode: boolean;
}

function displayName(item: RawItem): string {
  if (item.content_type === "text" && item.content_text) return item.content_text.slice(0, 60);
  if (item.content_type === "url") return item.content_text || "(url)";
  return item.content_text || `[${item.content_type}]`;
}

export default function FileCard({ item, selected, onToggleSelect, selectMode }: Props) {
  return (
    <div
      className={`group relative bg-m3-surface border rounded-xl p-4 h-40 flex flex-col ${
        selected ? "border-m3-accent" : "border-m3-border"
      } hover:border-m3-muted transition-colors`}
    >
      <div
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect(item.id);
        }}
        className={`absolute top-2 right-2 w-5 h-5 rounded border flex items-center justify-center cursor-pointer ${
          selected
            ? "bg-m3-accent border-m3-accent text-white"
            : "border-m3-border opacity-0 group-hover:opacity-100"
        } ${selectMode ? "opacity-100" : ""}`}
      >
        {selected && "✓"}
      </div>
      <Link to={`/documents/${item.id}`} className="flex-1 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <span className="text-2xl"><TypeIcon contentType={item.content_type} /></span>
          <StatusBadge status={item.status} />
        </div>
        <div className="text-sm font-medium line-clamp-2 mb-1">{displayName(item)}</div>
        <div className="text-xs text-m3-muted mt-auto">
          {item.content_type}{item.user_project ? ` · ${item.user_project}` : ""}
        </div>
      </Link>
    </div>
  );
}
