// List view for /api/v1/items. Filter bar (content kind multiselect, search,
// archived toggle) + paginated row list. Newest first by created_at.

import { useEffect, useState } from "react";
import { api, type ItemListEntry } from "../../../api/client";

const CONTENT_KINDS = [
  { id: "pdf", label: "PDF" },
  { id: "image", label: "Image" },
  { id: "audio", label: "Audio" },
  { id: "video", label: "Video" },
  { id: "text", label: "Text" },
  { id: "docx", label: "Doc" },
  { id: "file", label: "Other" },
];

const KIND_ICONS: Record<string, string> = {
  pdf: "PDF",
  image: "IMG",
  audio: "AUD",
  video: "VID",
  text: "TXT",
  docx: "DOC",
  file: "FILE",
};

export interface FilesListProps {
  refreshToken: number;
  selectedId: string | null;
  onSelect: (entry: ItemListEntry) => void;
  onArchiveChanged: () => void;
}

export function FilesList({ refreshToken, selectedId, onSelect, onArchiveChanged }: FilesListProps) {
  const [entries, setEntries] = useState<ItemListEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filterKinds, setFilterKinds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  // Reset and reload whenever the filter state or refresh token changes. We
  // deliberately don't paginate-then-filter; cheaper to refetch from the top.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listItems({
        content_kind: filterKinds.size ? Array.from(filterKinds) : undefined,
        q: search.trim() || undefined,
        include_archived: includeArchived,
        limit: 50,
      })
      .then(page => {
        if (cancelled) return;
        setEntries(page.items);
        setNextCursor(page.next_cursor);
        setLoading(false);
      })
      .catch(e => {
        if (cancelled) return;
        setError(String(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken, filterKinds, search, includeArchived]);

  async function loadMore() {
    if (!nextCursor) return;
    setLoading(true);
    try {
      const page = await api.listItems({
        content_kind: filterKinds.size ? Array.from(filterKinds) : undefined,
        q: search.trim() || undefined,
        include_archived: includeArchived,
        cursor: nextCursor,
        limit: 50,
      });
      setEntries(prev => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function toggleKind(id: string) {
    setFilterKinds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function archive(e: ItemListEntry) {
    try {
      await api.archiveItem(e.id, !e.archived);
      onArchiveChanged();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="m3-files__list">
      <div className="m3-files__filters">
        <input
          className="m3-input m3-files__search"
          placeholder="Search filename or text…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div className="m3-files__chips">
          {CONTENT_KINDS.map(k => (
            <button
              key={k.id}
              type="button"
              className={`m3-files__chip${filterKinds.has(k.id) ? " m3-files__chip--on" : ""}`}
              onClick={() => toggleKind(k.id)}
            >
              {k.label}
            </button>
          ))}
          <label className="m3-files__archived-toggle">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={e => setIncludeArchived(e.target.checked)}
            />
            <span>Show archived</span>
          </label>
        </div>
      </div>

      {error && <div className="m3-files__error">{error}</div>}

      <ul className="m3-files__rows">
        {entries.map(e => (
          <li
            key={e.id}
            className={`m3-files__row${selectedId === e.id ? " m3-files__row--selected" : ""}${
              e.archived ? " m3-files__row--archived" : ""
            }`}
            onClick={() => onSelect(e)}
          >
            <div className="m3-files__row-thumb">
              {e.has_thumbnail ? (
                <img src={api.itemThumbnailUrl(e.id)} alt="" />
              ) : (
                <span className="m3-files__row-icon">{KIND_ICONS[e.content_kind] || "·"}</span>
              )}
            </div>
            <div className="m3-files__row-main">
              <div className="m3-files__row-name">
                {e.original_filename || `(${e.content_kind} item)`}
              </div>
              <div className="m3-files__row-meta">
                <span>{formatDate(e.created_at)}</span>
                <span>·</span>
                <span>{e.content_kind}</span>
                {e.entity_count > 0 && (
                  <>
                    <span>·</span>
                    <span>{e.entity_count} entity hooks</span>
                  </>
                )}
                {e.archived && (
                  <>
                    <span>·</span>
                    <span>archived</span>
                  </>
                )}
              </div>
            </div>
            <button
              type="button"
              className="m3-btn-ghost m3-files__row-action"
              onClick={ev => {
                ev.stopPropagation();
                archive(e);
              }}
              title={e.archived ? "Unarchive" : "Archive"}
            >
              {e.archived ? "Unarchive" : "Archive"}
            </button>
          </li>
        ))}
        {!loading && entries.length === 0 && (
          <li className="m3-files__row-empty">
            No files yet. Drop something into the dropzone above.
          </li>
        )}
      </ul>

      {nextCursor && (
        <div className="m3-files__more">
          <button className="m3-btn" onClick={loadMore} disabled={loading}>
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}
