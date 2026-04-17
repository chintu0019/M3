import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ItemDetail } from "../api/client";
import ErrorCard from "../components/detail/ErrorCard";
import ExtractedContent from "../components/detail/ExtractedContent";
import FilePreview from "../components/detail/FilePreview";
import NotesPanel from "../components/detail/NotesPanel";
import ProcessingTimeline from "../components/detail/ProcessingTimeline";
import UserInputsCard from "../components/detail/UserInputsCard";
import StatusBadge from "../components/library/StatusBadge";

export default function LibraryDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setItem(await api.library.get(id));
      setError(null);
    } catch (err) {
      setError(`${err}`);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while processing
  useEffect(() => {
    if (!item) return;
    if (item.status !== "pending" && item.status !== "processing") return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [item, load]);

  if (loading) return <div className="p-6 text-m3-muted">Loading...</div>;
  if (error || !item) return <div className="p-6 text-red-400">{error || "Not found"}</div>;

  const name = item.content_text?.slice(0, 80) || `[${item.content_type}]`;
  const canReprocess = item.status !== "processing";

  const retry = async () => {
    try {
      await api.library.retry(item.id);
      load();
    } catch (err) {
      alert(`Retry failed: ${err}`);
    }
  };

  const onDelete = async () => {
    if (!confirm("Delete this item? This cannot be undone.")) return;
    try {
      await api.library.delete(item.id);
      navigate("/library");
    } catch (err) {
      alert(`Delete failed: ${err}`);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <button onClick={() => navigate(-1)} className="text-m3-muted hover:text-m3-text mb-4 text-sm">
        ← Back to Library
      </button>

      <header className="flex items-start justify-between gap-4 mb-6 pb-4 border-b border-m3-border">
        <div className="min-w-0">
          <h1 className="text-xl font-bold truncate mb-1">{name}</h1>
          <div className="flex flex-wrap items-center gap-2 text-xs text-m3-muted">
            <StatusBadge status={item.status} />
            <span>{item.content_type || "?"}</span>
            <span>· via {item.source_channel}</span>
            <span>· {new Date(item.created_at).toLocaleString()}</span>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          {item.file_url && (
            <a href={item.file_url} target="_blank" rel="noopener noreferrer" className="text-sm px-3 py-1.5 bg-m3-surface border border-m3-border rounded hover:border-m3-muted">
              ⬇ Download
            </a>
          )}
          <button onClick={retry} disabled={item.status === "processing"} className="text-sm px-3 py-1.5 bg-m3-surface border border-m3-border rounded hover:border-m3-muted disabled:opacity-40">
            ↻ Reprocess
          </button>
          <button onClick={onDelete} className="text-sm px-3 py-1.5 bg-red-900/20 border border-red-900/50 text-red-400 rounded hover:border-red-500">
            🗑
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="md:col-span-2 space-y-4">
          {item.status === "error" && item.error_message ? (
            <ErrorCard message={item.error_message} onRetry={retry} />
          ) : (
            <FilePreview item={item} />
          )}
          <UserInputsCard userTags={item.user_tags} userProject={item.user_project} />
          <ExtractedContent content={item.content_text} />
          <ProcessingTimeline item={item} />
        </div>

        <div className="space-y-4">
          <NotesPanel
            itemId={item.id}
            notes={item.notes}
            onRefresh={load}
            onReprocess={retry}
            canReprocess={canReprocess}
          />
          <div className="bg-m3-surface border border-m3-border rounded-xl p-4 text-xs text-m3-muted">
            <div className="mb-1"><span className="uppercase tracking-wide">ID</span></div>
            <code className="font-mono break-all">{item.id}</code>
          </div>
        </div>
      </div>
    </div>
  );
}
