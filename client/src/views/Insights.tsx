import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type EntitySummary, type InsightSummary } from "../api/client";

const STATUS_TABS = [
  { key: "new", label: "New" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "dismissed", label: "Dismissed" },
  { key: "", label: "All" },
] as const;

const TYPE_COLORS: Record<string, string> = {
  contradiction: "bg-red-500/20 text-red-300 border-red-500/40",
  connection: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  stale: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  pattern: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
  orphan: "bg-slate-500/20 text-slate-300 border-slate-500/40",
  suggestion: "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40",
  person: "bg-sky-500/20 text-sky-300 border-sky-500/40",
};

function typeClass(type: string): string {
  return TYPE_COLORS[type] ?? "bg-slate-500/20 text-slate-300 border-slate-500/40";
}

export default function Insights() {
  const [statusFilter, setStatusFilter] = useState<string>("new");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [items, setItems] = useState<InsightSummary[]>([]);
  const [entitiesById, setEntitiesById] = useState<Record<string, EntitySummary>>({});

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = { per_page: "100" };
      if (statusFilter) params.status = statusFilter;
      if (typeFilter) params.insight_type = typeFilter;
      const res = await api.insights.list(params);
      setItems(res.items);
    } catch {
      setItems([]);
    }
  }, [statusFilter, typeFilter]);

  useEffect(() => { load(); }, [load]);

  // Resolve entity ids -> names so the feed can link to them.
  useEffect(() => {
    (async () => {
      try {
        const res = await api.entities.list({ per_page: "500" });
        const by: Record<string, EntitySummary> = {};
        for (const e of res.items) by[e.id] = e;
        setEntitiesById(by);
      } catch {
        // ignore
      }
    })();
  }, []);

  const availableTypes = useMemo(
    () => [...new Set(items.map((i) => i.insight_type))].sort(),
    [items],
  );

  const patch = async (id: string, newStatus: string) => {
    try {
      await api.insights.patch(id, newStatus);
      load();
    } catch {
      // ignore
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <header className="mb-4">
        <h1 className="text-2xl font-bold">Insights</h1>
        <p className="text-sm text-m3-muted">
          Patterns, contradictions, and suggestions surfaced after recent ingests.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-4 mb-4">
        <div className="flex gap-1 rounded-md border border-m3-border p-0.5 bg-m3-surface">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setStatusFilter(t.key)}
              className={`px-3 py-1 text-sm rounded-sm transition-colors ${
                statusFilter === t.key
                  ? "bg-m3-accent text-white"
                  : "text-m3-muted hover:text-m3-text"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {availableTypes.length > 0 && (
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setTypeFilter(null)}
              className={`text-xs px-2 py-1 rounded border ${
                typeFilter === null
                  ? "bg-m3-accent text-white border-m3-accent"
                  : "text-m3-muted border-m3-border hover:text-m3-text"
              }`}
            >
              all types
            </button>
            {availableTypes.map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t === typeFilter ? null : t)}
                className={`text-xs px-2 py-1 rounded border ${
                  typeFilter === t
                    ? "bg-m3-accent text-white border-m3-accent"
                    : "text-m3-muted border-m3-border hover:text-m3-text"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>

      {items.length === 0 && (
        <div className="rounded-md border border-m3-border bg-m3-surface/40 p-6 text-m3-muted text-sm">
          No insights for this filter. Capable-provider ingests populate this
          feed automatically.
        </div>
      )}

      <ul className="space-y-3">
        {items.map((i) => (
          <li key={i.id} className="rounded-md border border-m3-border bg-m3-surface p-4">
            <div className="flex items-start gap-3">
              <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border whitespace-nowrap ${typeClass(i.insight_type)}`}>
                {i.insight_type}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium mb-1">{i.title}</div>
                <div className="text-sm text-m3-muted whitespace-pre-wrap mb-2">
                  {i.description}
                </div>
                {i.related_entity_ids.length > 0 && (
                  <div className="text-xs text-m3-muted">
                    Entities:{" "}
                    {i.related_entity_ids.map((eid, idx) => {
                      const e = entitiesById[eid];
                      if (!e) return null;
                      return (
                        <span key={eid}>
                          <Link to={`/entities/${eid}`} className="text-m3-accent hover:underline">
                            {e.canonical_name}
                          </Link>
                          {idx < i.related_entity_ids.length - 1 && ", "}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-m3-muted">{i.status}</span>
                {i.status !== "acknowledged" && (
                  <button
                    onClick={() => patch(i.id, "acknowledged")}
                    className="text-xs px-2 py-0.5 rounded border border-m3-border hover:border-m3-accent hover:text-m3-accent"
                  >
                    ack
                  </button>
                )}
                {i.status !== "dismissed" && (
                  <button
                    onClick={() => patch(i.id, "dismissed")}
                    className="text-xs px-2 py-0.5 rounded border border-m3-border hover:border-red-400 hover:text-red-400"
                  >
                    dismiss
                  </button>
                )}
                {i.status !== "new" && (
                  <button
                    onClick={() => patch(i.id, "new")}
                    className="text-xs px-2 py-0.5 rounded border border-m3-border hover:border-m3-muted"
                  >
                    reopen
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
