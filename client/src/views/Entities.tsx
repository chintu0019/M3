import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  type EntityDetail,
  type EntitySummary,
  type InsightSummary,
} from "../api/client";

// Colour-map entity types into stable accents. Unknown types fall through
// to a neutral. The palette is the same one used by the graph view so the
// two feel consistent.
const TYPE_COLORS: Record<string, string> = {
  person: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  project: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
  company: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  concept: "bg-sky-500/20 text-sky-300 border-sky-500/40",
  place: "bg-rose-500/20 text-rose-300 border-rose-500/40",
  event: "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40",
  topic: "bg-slate-500/20 text-slate-300 border-slate-500/40",
};

function typeClass(type: string): string {
  return TYPE_COLORS[type] ?? "bg-slate-500/20 text-slate-300 border-slate-500/40";
}

export default function Entities() {
  const { entityId } = useParams();
  const navigate = useNavigate();

  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const loadList = useCallback(async () => {
    try {
      const params: Record<string, string> = { per_page: "200" };
      if (typeFilter) params.entity_type = typeFilter;
      const res = await api.entities.list(params);
      setEntities(res.items);
    } catch {
      setEntities([]);
    }
  }, [typeFilter]);

  useEffect(() => { loadList(); }, [loadList]);

  useEffect(() => {
    if (!entityId) { setDetail(null); return; }
    api.entities.get(entityId).then(setDetail).catch(() => setDetail(null));
  }, [entityId]);

  const grouped = useMemo(() => {
    const filter = search.trim().toLowerCase();
    const out = new Map<string, EntitySummary[]>();
    for (const e of entities) {
      if (filter && !e.canonical_name.toLowerCase().includes(filter) &&
          !e.aliases.some((a) => a.toLowerCase().includes(filter))) {
        continue;
      }
      const k = e.entity_type || "topic";
      const arr = out.get(k) ?? [];
      arr.push(e);
      out.set(k, arr);
    }
    return [...out.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [entities, search]);

  const types = useMemo(
    () => [...new Set(entities.map((e) => e.entity_type))].sort(),
    [entities],
  );

  return (
    <div className="flex h-[calc(100vh-57px)]">
      {/* Sidebar */}
      <aside className="w-72 border-r border-m3-border bg-m3-surface/40 flex flex-col">
        <div className="p-3 border-b border-m3-border space-y-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter entities..."
            className="w-full px-3 py-2 text-sm rounded-md bg-m3-bg border border-m3-border focus:outline-none focus:border-m3-accent"
          />
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setTypeFilter(null)}
              className={`text-xs px-2 py-1 rounded-md border ${
                typeFilter === null
                  ? "bg-m3-accent text-white border-m3-accent"
                  : "text-m3-muted border-m3-border hover:text-m3-text"
              }`}
            >
              all
            </button>
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t === typeFilter ? null : t)}
                className={`text-xs px-2 py-1 rounded-md border ${
                  typeFilter === t
                    ? "bg-m3-accent text-white border-m3-accent"
                    : "text-m3-muted border-m3-border hover:text-m3-text"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {grouped.length === 0 && (
            <div className="p-4 text-sm text-m3-muted">
              {entities.length === 0
                ? "No entities yet. Share a note in wiki_mode=entity to populate."
                : "No matches."}
            </div>
          )}
          {grouped.map(([type, rows]) => (
            <div key={type} className="py-2">
              <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-m3-muted">
                {type}
              </div>
              {rows.map((e) => (
                <button
                  key={e.id}
                  onClick={() => navigate(`/entities/${e.id}`)}
                  className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 ${
                    entityId === e.id ? "bg-m3-accent/20 text-white" : "hover:bg-m3-surface"
                  }`}
                >
                  <span className="flex-1 truncate">{e.canonical_name}</span>
                  {e.facts_since_render > 0 && (
                    <span className="text-[10px] bg-m3-accent/30 text-m3-accent-hover px-1.5 rounded">
                      {e.facts_since_render}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto">
        {!detail ? (
          <div className="p-8 text-m3-muted text-sm">
            Pick an entity from the sidebar.
          </div>
        ) : (
          <article className="max-w-3xl p-8">
            <header className="mb-6">
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold">{detail.canonical_name}</h1>
                <span className={`text-xs px-2 py-0.5 rounded-md border ${typeClass(detail.entity_type)}`}>
                  {detail.entity_type}
                </span>
                {detail.page_dirty && (
                  <span className="text-xs px-2 py-0.5 rounded-md border border-amber-500/40 bg-amber-500/20 text-amber-300">
                    re-rendering
                  </span>
                )}
              </div>
              {detail.aliases.length > 0 && (
                <div className="text-sm text-m3-muted mt-1">
                  Also: {detail.aliases.join(", ")}
                </div>
              )}
              {detail.description && (
                <p className="text-m3-muted mt-2">{detail.description}</p>
              )}
            </header>

            {detail.page_content ? (
              <div className="prose prose-invert prose-m3 max-w-none">
                <PageContent markdown={detail.page_content} />
              </div>
            ) : (
              <p className="text-m3-muted italic">
                No page yet. The renderer picks up dirty entities every 5 minutes.
              </p>
            )}
          </article>
        )}
      </main>

      {/* Right rail */}
      {detail && (
        <aside className="w-72 border-l border-m3-border bg-m3-surface/40 overflow-y-auto">
          <div className="p-4">
            <h2 className="text-xs uppercase tracking-wide text-m3-muted mb-2">
              Related ({detail.related.length})
            </h2>
            {detail.related.length === 0 && (
              <div className="text-sm text-m3-muted italic">none yet</div>
            )}
            <ul className="space-y-1">
              {detail.related.map((r) => (
                <li key={`${r.id}-${r.link_type}`}>
                  <Link
                    to={`/entities/${r.id}`}
                    className="block text-sm hover:text-m3-accent"
                  >
                    <span className="truncate">{r.canonical_name}</span>
                    <span className="text-xs text-m3-muted ml-1">
                      ({r.link_type}, w={r.weight})
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div className="p-4 border-t border-m3-border">
            <h2 className="text-xs uppercase tracking-wide text-m3-muted mb-2">
              Insights ({detail.insights.length})
            </h2>
            {detail.insights.length === 0 && (
              <div className="text-sm text-m3-muted italic">no open insights</div>
            )}
            <ul className="space-y-2">
              {detail.insights.map((i) => (
                <li key={i.id}>
                  <InsightCard insight={i} />
                </li>
              ))}
            </ul>
          </div>
        </aside>
      )}
    </div>
  );
}

const CITATION_RE = /\[\^([0-9a-fA-F-]{30,36})\]/g;

function PageContent({ markdown }: { markdown: string }) {
  // Pre-transform [^<uuid>] markers into real inline markdown links so
  // they render as clickable source chips. remark-gfm's native footnote
  // handling requires matching definitions; we don't emit those, so this
  // is simpler and more predictable.
  const transformed = markdown.replace(
    CITATION_RE,
    (_m, uuid: string) => `[[source]](/library/${uuid})`,
  );
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children, ...rest }) => {
          if (href && href.startsWith("/library/")) {
            return (
              <Link
                to={href}
                className="text-m3-accent hover:underline text-xs ml-1"
                title="Source item"
              >
                {children}
              </Link>
            );
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
              {children}
            </a>
          );
        },
      }}
    >
      {transformed}
    </ReactMarkdown>
  );
}

function InsightCard({ insight }: { insight: InsightSummary }) {
  const [status, setStatus] = useState(insight.status);
  const patch = async (newStatus: string) => {
    try {
      const updated = await api.insights.patch(insight.id, newStatus);
      setStatus(updated.status);
    } catch {
      // ignore
    }
  };
  return (
    <div className="rounded-md border border-m3-border bg-m3-bg p-2">
      <div className="flex items-center gap-2 mb-1">
        <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${typeClass(insight.insight_type)}`}>
          {insight.insight_type}
        </span>
        <span className="text-xs text-m3-muted">{status}</span>
      </div>
      <div className="text-sm font-medium mb-1">{insight.title}</div>
      <div className="text-xs text-m3-muted whitespace-pre-wrap">{insight.description}</div>
      <div className="flex gap-2 mt-2">
        {status !== "acknowledged" && (
          <button
            onClick={() => patch("acknowledged")}
            className="text-xs px-2 py-0.5 rounded border border-m3-border hover:border-m3-accent hover:text-m3-accent"
          >
            ack
          </button>
        )}
        {status !== "dismissed" && (
          <button
            onClick={() => patch("dismissed")}
            className="text-xs px-2 py-0.5 rounded border border-m3-border hover:border-red-400 hover:text-red-400"
          >
            dismiss
          </button>
        )}
      </div>
    </div>
  );
}
