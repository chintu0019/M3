import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";

export default function EntityDetail() {
  const { slug = "" } = useParams();
  const { data, error, loading } = useApi(() => api.entity(slug), [slug]);
  if (loading) return <div className="p-6 text-m3-muted">loading…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (!data) return null;
  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="text-sm text-m3-muted mb-2">
        <Link to="/entities" className="hover:text-m3-text">← Entities</Link>
      </div>
      <h1 className="text-2xl font-bold">{data.canonical_name}</h1>
      <div className="text-sm text-m3-muted mb-4">
        {data.entity_type}
        {data.aliases.length > 0 && <> · aka {data.aliases.join(", ")}</>}
      </div>
      {data.description && <p className="mb-4 text-m3-text">{data.description}</p>}
      {data.summary_external && (
        <div className="bg-m3-surface rounded p-4 mb-4 text-sm">
          <div className="text-xs uppercase text-m3-muted mb-1">Neutral summary</div>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.summary_external}</ReactMarkdown>
        </div>
      )}
      {data.body && (
        <div className="text-sm leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.body}</ReactMarkdown>
        </div>
      )}
      {data.related.length > 0 && (
        <section className="mt-6">
          <h3 className="text-sm uppercase text-m3-muted mb-2">Related</h3>
          <ul className="space-y-1">
            {data.related.map((slug) => (
              <li key={slug}>
                <Link to={`/entities/${slug}`} className="text-m3-accent hover:text-m3-accent-hover">
                  {slug}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
