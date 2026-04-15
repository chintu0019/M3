import { Link } from "react-router-dom";
import { type LinkedWikiPage } from "../../api/client";

export default function WikiPagesList({ pages }: { pages: LinkedWikiPage[] }) {
  if (pages.length === 0) return null;
  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-m3-muted mb-2">Wiki Pages</div>
      <div className="flex flex-col gap-2">
        {pages.map((p) => (
          <Link
            key={p.id}
            to={`/wiki/${p.id}`}
            className="flex items-center gap-2 text-sm text-m3-accent hover:text-m3-accent-hover"
          >
            <span>→</span>
            <span className="flex-1 truncate">{p.title}</span>
            {p.category && <span className="text-xs text-m3-muted">{p.category}</span>}
          </Link>
        ))}
      </div>
    </div>
  );
}
