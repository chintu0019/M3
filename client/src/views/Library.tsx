import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type RawItem } from "../api/client";
import CaptureForm from "../components/library/CaptureForm";
import FileList from "../components/library/FileList";
import Sidebar from "../components/library/Sidebar";
import { useLibraryFilters } from "../hooks/useLibraryFilters";
import { useSidebarCollapse } from "../hooks/useSidebarCollapse";

function matchesFilter(item: RawItem, filters: ReturnType<typeof useLibraryFilters>["filters"]): boolean {
  const f = filters.filter;
  if (f.kind === "view") {
    switch (f.value) {
      case "all": return true;
      case "recent": {
        const cutoff = Date.now() - 24 * 3600 * 1000;
        return new Date(item.created_at).getTime() >= cutoff;
      }
      case "pending":
      case "processing":
      case "done":
      case "error":
        return item.status === f.value;
    }
  }
  if (f.kind === "project") {
    if (f.value === "(Unassigned)") return !item.user_project;
    return item.user_project === f.value;
  }
  if (f.kind === "source") {
    return item.source_channel === f.value;
  }
  if (f.kind === "type") {
    const t = item.content_type || "file";
    const DOC = new Set(["pdf", "docx", "xlsx", "pptx", "epub", "html", "file"]);
    switch (f.value) {
      case "documents": return DOC.has(t);
      case "images":    return t === "image";
      case "audio":     return t === "audio" || t === "voice";
      case "video":     return t === "video";
      case "links":     return t === "url";
      case "text":      return t === "text";
    }
    return false;
  }
  return true;
}

function matchesQuery(item: RawItem, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  const haystack = [
    item.content_text || "",
    item.content_type || "",
    item.user_project || "",
    ...(item.user_tags || []),
  ].join(" ").toLowerCase();
  return haystack.includes(needle);
}

function sortItems(items: RawItem[], sort: string): RawItem[] {
  const arr = [...items];
  switch (sort) {
    case "date_asc":
      return arr.sort((a, b) => a.created_at.localeCompare(b.created_at));
    case "name_asc":
      return arr.sort((a, b) => (a.content_text || "").localeCompare(b.content_text || ""));
    case "status":
      return arr.sort((a, b) => a.status.localeCompare(b.status));
    default:
      return arr.sort((a, b) => b.created_at.localeCompare(a.created_at));
  }
}

export default function Library() {
  const [items, setItems] = useState<RawItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { filters, setField } = useLibraryFilters();
  const [sidebarCollapsed, setSidebarCollapsed] = useSidebarCollapse();

  const load = useCallback(async () => {
    try {
      const res = await api.ingest.list({ per_page: "200" });
      setItems(res.items);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    load();
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [load]);

  const visible = useMemo(() => {
    const filtered = items.filter((i) => matchesFilter(i, filters) && matchesQuery(i, filters.q));
    return sortItems(filtered, filters.sort);
  }, [items, filters]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = () => setSelected(new Set());

  return (
    <div className="flex h-[calc(100vh-52px)]">
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto">
          <h1 className="text-2xl font-bold mb-4">Library</h1>

          <div className="mb-6">
            <CaptureForm onAfterSend={load} />
          </div>

          <div className="flex items-center gap-3 mb-4">
            <input
              value={filters.q}
              onChange={(e) => setField("q", e.target.value)}
              placeholder="Search the current view..."
              className="flex-1 bg-m3-surface border border-m3-border rounded-lg px-3 py-1.5 text-sm"
            />
            <select
              value={filters.sort}
              onChange={(e) => setField("sort", e.target.value)}
              className="bg-m3-surface border border-m3-border rounded-lg px-3 py-1.5 text-sm"
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="name_asc">Name A-Z</option>
              <option value="status">Status</option>
            </select>
            <div className="flex bg-m3-surface border border-m3-border rounded-lg overflow-hidden">
              <button
                onClick={() => setField("mode", "list")}
                className={`px-3 py-1.5 text-sm ${filters.mode === "list" ? "bg-m3-accent text-white" : "text-m3-muted hover:text-m3-text"}`}
                aria-label="List view"
              >
                ☰
              </button>
              <button
                onClick={() => setField("mode", "grid")}
                className={`px-3 py-1.5 text-sm ${filters.mode === "grid" ? "bg-m3-accent text-white" : "text-m3-muted hover:text-m3-text"}`}
                aria-label="Grid view"
              >
                ⊞
              </button>
            </div>
          </div>

          <div className="text-xs text-m3-muted mb-3">
            {visible.length} item{visible.length === 1 ? "" : "s"}
          </div>

          <FileList
            items={visible}
            mode={filters.mode}
            selected={selected}
            onToggleSelect={toggleSelect}
            selectMode={selected.size > 0}
          />

          {selected.size > 0 && (
            <BulkBar
              count={selected.size}
              onRetry={async () => {
                const ids = Array.from(selected);
                try {
                  await api.library.bulkRetry(ids);
                  clearSelection();
                  await load();
                } catch (err) {
                  alert(`Bulk retry failed: ${err}`);
                }
              }}
              onDelete={async () => {
                if (!confirm(`Delete ${selected.size} items?`)) return;
                const ids = Array.from(selected);
                try {
                  await api.library.bulkDelete(ids);
                  clearSelection();
                  await load();
                } catch (err) {
                  alert(`Bulk delete failed: ${err}`);
                }
              }}
              onClear={clearSelection}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function BulkBar({
  count,
  onRetry,
  onDelete,
  onClear,
}: {
  count: number;
  onRetry: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-m3-surface border border-m3-border rounded-xl shadow-xl px-4 py-3 flex items-center gap-3 text-sm z-40">
      <span>{count} selected</span>
      <button onClick={onRetry} className="px-3 py-1 bg-m3-bg border border-m3-border rounded hover:border-m3-muted">
        ↻ Retry
      </button>
      <button onClick={onDelete} className="px-3 py-1 bg-red-900/20 border border-red-900/50 text-red-400 rounded hover:border-red-500">
        🗑 Delete
      </button>
      <button onClick={onClear} className="text-m3-muted hover:text-m3-text">
        ×
      </button>
    </div>
  );
}
