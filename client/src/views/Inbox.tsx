import { useCallback, useEffect, useRef, useState } from "react";
import { api, type RawItem } from "../api/client";

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-900/50 text-yellow-300",
    processing: "bg-blue-900/50 text-blue-300",
    done: "bg-green-900/50 text-green-300",
    error: "bg-red-900/50 text-red-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] || "bg-m3-surface text-m3-muted"}`}>
      {status}
    </span>
  );
}

export default function Inbox() {
  const [items, setItems] = useState<RawItem[]>([]);
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [project, setProject] = useState("");
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadItems = useCallback(async () => {
    try {
      const res = await api.ingest.list({ per_page: "50" });
      setItems(res.items);
    } catch {
      // API might not be ready
    }
  }, []);

  useEffect(() => {
    loadItems();
    const interval = setInterval(loadItems, 5000);
    return () => clearInterval(interval);
  }, [loadItems]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;

    setSending(true);
    try {
      await api.ingest.create(text, tags || undefined, project || undefined);
      setText("");
      setTags("");
      setProject("");
      await loadItems();
    } catch (err) {
      alert(`Failed to submit: ${err}`);
    }
    setSending(false);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setSending(true);
    try {
      await api.ingest.upload(file, tags || undefined, project || undefined);
      await loadItems();
    } catch (err) {
      alert(`Upload failed: ${err}`);
    }
    setSending(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Inbox</h1>

      {/* Quick capture */}
      <form onSubmit={handleSubmit} className="mb-8 bg-m3-surface rounded-xl p-4 border border-m3-border">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Share something with M3..."
          className="w-full bg-transparent border-none outline-none resize-none text-m3-text placeholder-m3-muted mb-3"
          rows={3}
        />
        <div className="flex gap-3 items-center">
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="Tags (comma-separated)"
            className="flex-1 bg-m3-bg border border-m3-border rounded-lg px-3 py-1.5 text-sm"
          />
          <input
            value={project}
            onChange={(e) => setProject(e.target.value)}
            placeholder="Project"
            className="flex-1 bg-m3-bg border border-m3-border rounded-lg px-3 py-1.5 text-sm"
          />
          <input
            ref={fileRef}
            type="file"
            onChange={handleFileUpload}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="px-3 py-1.5 bg-m3-bg border border-m3-border rounded-lg text-sm hover:bg-m3-border transition-colors"
          >
            Upload
          </button>
          <button
            type="submit"
            disabled={sending || !text.trim()}
            className="px-4 py-1.5 bg-m3-accent text-white rounded-lg text-sm hover:bg-m3-accent-hover transition-colors disabled:opacity-50"
          >
            {sending ? "Sending..." : "Send"}
          </button>
        </div>
      </form>

      {/* Items list */}
      <div className="space-y-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="bg-m3-surface border border-m3-border rounded-lg p-4 flex items-start gap-3"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <StatusBadge status={item.status} />
                <span className="text-xs text-m3-muted">
                  {item.content_type} via {item.source_channel}
                </span>
                <span className="text-xs text-m3-muted">
                  {new Date(item.created_at).toLocaleString()}
                </span>
              </div>
              <p className="text-sm truncate">
                {item.content_text || `[${item.content_type} file]`}
              </p>
              {item.user_tags.length > 0 && (
                <div className="flex gap-1 mt-1">
                  {item.user_tags.map((tag) => (
                    <span key={tag} className="text-xs bg-m3-bg px-2 py-0.5 rounded">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {item.error_message && (
                <p className="text-xs text-red-400 mt-1">{item.error_message}</p>
              )}
            </div>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-m3-muted text-center py-12">
            Nothing here yet. Share something above to get started.
          </p>
        )}
      </div>
    </div>
  );
}
