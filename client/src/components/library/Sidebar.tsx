import { api, type LibraryStats } from "../../api/client";
import { useCallback, useEffect, useState } from "react";
import { useLibraryFilters, type SidebarFilter } from "../../hooks/useLibraryFilters";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

function Entry({
  label,
  count,
  active,
  onClick,
  icon,
  indent = false,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  icon?: string;
  indent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-2 py-1.5 rounded text-sm flex items-center gap-2 ${
        active
          ? "bg-m3-accent/20 text-m3-accent"
          : "text-m3-text hover:bg-m3-bg"
      } ${indent ? "pl-3" : ""}`}
    >
      {icon && <span className="w-4 text-center">{icon}</span>}
      <span className="flex-1 truncate">{label}</span>
      {typeof count === "number" && (
        <span className="text-xs text-m3-muted">{count}</span>
      )}
    </button>
  );
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { filters, setFilter } = useLibraryFilters();
  const [stats, setStats] = useState<LibraryStats | null>(null);

  const load = useCallback(async () => {
    try {
      setStats(await api.library.stats());
    } catch {
      // not ready
    }
  }, []);

  useEffect(() => {
    load();
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [load]);

  const activeMatch = (f: SidebarFilter) => {
    const cur = filters.filter;
    return cur.kind === f.kind && (f as { value?: string }).value === (cur as { value?: string }).value;
  };

  if (collapsed) {
    return (
      <div className="w-12 shrink-0 border-r border-m3-border bg-m3-surface flex flex-col items-center py-3">
        <button
          onClick={onToggle}
          className="text-m3-muted hover:text-m3-text p-2 rounded hover:bg-m3-bg"
          aria-label="Expand sidebar"
        >
          ☰
        </button>
      </div>
    );
  }

  return (
    <div className="w-64 shrink-0 border-r border-m3-border bg-m3-surface p-3 overflow-y-auto flex flex-col gap-4">
      <button
        onClick={onToggle}
        className="self-start text-m3-muted hover:text-m3-text p-1 rounded hover:bg-m3-bg text-sm"
        aria-label="Collapse sidebar"
      >
        ← Collapse
      </button>

      {stats && (
        <>
          <section>
            <div className="text-xs uppercase tracking-wide text-m3-muted mb-2">Views</div>
            <Entry label="All files" count={stats.totals.all} icon="●"
              active={activeMatch({ kind: "view", value: "all" })}
              onClick={() => setFilter({ kind: "view", value: "all" })}
            />
            <Entry label="Recent" count={stats.totals.recent} icon="⏱"
              active={activeMatch({ kind: "view", value: "recent" })}
              onClick={() => setFilter({ kind: "view", value: "recent" })}
            />
            <Entry label="Processing" count={stats.totals.processing} icon="◐"
              active={activeMatch({ kind: "view", value: "processing" })}
              onClick={() => setFilter({ kind: "view", value: "processing" })}
            />
            <Entry label="Failed" count={stats.totals.error} icon="⚠"
              active={activeMatch({ kind: "view", value: "error" })}
              onClick={() => setFilter({ kind: "view", value: "error" })}
            />
            <Entry label="Done" count={stats.totals.done} icon="✓"
              active={activeMatch({ kind: "view", value: "done" })}
              onClick={() => setFilter({ kind: "view", value: "done" })}
            />
          </section>

          {stats.projects.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-m3-muted mb-2">Projects</div>
              {stats.projects.map((p) => (
                <Entry key={p.key} label={p.key} count={p.count}
                  active={activeMatch({ kind: "project", value: p.key })}
                  onClick={() => setFilter({ kind: "project", value: p.key })}
                />
              ))}
            </section>
          )}

          {stats.types.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-m3-muted mb-2">Type</div>
              {stats.types.map((t) => (
                <Entry key={t.key} label={t.key} count={t.count}
                  active={activeMatch({ kind: "type", value: t.key })}
                  onClick={() => setFilter({ kind: "type", value: t.key })}
                />
              ))}
            </section>
          )}

          {stats.sources.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-m3-muted mb-2">Source</div>
              {stats.sources.map((s) => (
                <Entry key={s.key} label={s.key} count={s.count}
                  active={activeMatch({ kind: "source", value: s.key })}
                  onClick={() => setFilter({ kind: "source", value: s.key })}
                />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
}
