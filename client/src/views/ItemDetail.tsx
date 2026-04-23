import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";

export default function ItemDetail() {
  const { id = "" } = useParams();
  const { data, error, loading } = useApi(() => api.item(id), [id]);
  if (loading) return <div className="p-6 text-m3-muted">loading…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!data) return null;

  const hookEntries = Object.entries(data.hooks || {});

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="text-sm text-m3-muted mb-2">
        <Link to="/search" className="hover:text-m3-text">← Search</Link>
      </div>
      <h1 className="text-2xl font-bold mb-1">{data.kind}</h1>
      <div className="text-sm text-m3-muted mb-4">
        {data.source}
        {" · "}
        captured {data.created_at}
        {data.when_iso && (
          <>
            {" · "}
            when {data.when_iso} ({data.when_source})
          </>
        )}
        {" · "}
        confidence {data.confidence.toFixed(2)}
      </div>

      {data.original_filename && (
        <div className="mb-4 text-sm">
          <a
            href={api.itemOriginalUrl(data.id)}
            target="_blank"
            rel="noopener noreferrer"
            className="text-m3-accent hover:text-m3-accent-hover"
          >
            View original · {data.original_filename}
          </a>
        </div>
      )}

      <section className="mb-6">
        <h3 className="text-xs uppercase text-m3-muted mb-2">Extracted text</h3>
        <textarea
          readOnly
          value={data.extracted_text}
          className="w-full h-64 bg-m3-surface border border-m3-border rounded p-3 text-sm font-mono"
        />
      </section>

      {hookEntries.length > 0 && (
        <section className="mb-6">
          <h3 className="text-xs uppercase text-m3-muted mb-2">Hooks</h3>
          <ul className="space-y-1 text-sm">
            {hookEntries.map(([k, v]) => (
              <li key={k} className="flex gap-2">
                <span className="text-m3-muted min-w-[8rem]">{k}</span>
                <span className="text-m3-text break-all">
                  {typeof v === "string" ? v : JSON.stringify(v)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
