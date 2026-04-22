import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";

export default function Entities() {
  const { data, error, loading } = useApi(() => api.entities());
  if (loading) return <div className="p-6 text-m3-muted">loading…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!data || data.entities.length === 0) {
    return <div className="p-6 text-m3-muted">No entities yet. Ingest a note first.</div>;
  }
  const byType = data.entities.reduce<Record<string, typeof data.entities>>((acc, e) => {
    (acc[e.entity_type] ||= []).push(e);
    return acc;
  }, {});
  const types = Object.keys(byType).sort();
  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Entities</h1>
      {types.map((t) => (
        <section key={t} className="mb-8">
          <h2 className="text-sm uppercase text-m3-muted mb-2">{t}</h2>
          <ul className="space-y-1">
            {byType[t].map((e) => (
              <li key={e.slug}>
                <Link
                  to={`/entities/${e.slug}`}
                  className="hover:bg-m3-surface px-3 py-2 rounded block"
                >
                  <span className="font-medium">{e.canonical_name}</span>
                  {e.aliases.length > 0 && (
                    <span className="text-m3-muted text-sm ml-2">
                      aka {e.aliases.join(", ")}
                    </span>
                  )}
                  {e.description && (
                    <div className="text-m3-muted text-sm">{e.description}</div>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
