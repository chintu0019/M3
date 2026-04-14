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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface PendingFile {
  id: string;
  file: File;
  status: "queued" | "uploading" | "done" | "error";
  error?: string;
}

export default function Inbox() {
  const [items, setItems] = useState<RawItem[]>([]);
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [project, setProject] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

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

  const addFiles = (files: FileList | File[]) => {
    const newPending: PendingFile[] = Array.from(files).map((file) => ({
      id: `${file.name}-${file.size}-${Date.now()}-${Math.random()}`,
      file,
      status: "queued",
    }));
    setPendingFiles((prev) => [...prev, ...newPending]);
  };

  const removeFile = (id: string) => {
    setPendingFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const uploadAll = async () => {
    if (pendingFiles.length === 0) return;

    setSending(true);
    const toUpload = pendingFiles.filter((f) => f.status === "queued" || f.status === "error");

    await Promise.all(
      toUpload.map(async (pf) => {
        setPendingFiles((prev) =>
          prev.map((f) => (f.id === pf.id ? { ...f, status: "uploading" } : f)),
        );
        try {
          await api.ingest.upload(pf.file, tags || undefined, project || undefined);
          setPendingFiles((prev) =>
            prev.map((f) => (f.id === pf.id ? { ...f, status: "done" } : f)),
          );
        } catch (err) {
          setPendingFiles((prev) =>
            prev.map((f) => (f.id === pf.id ? { ...f, status: "error", error: `${err}` } : f)),
          );
        }
      }),
    );

    // Clear successfully uploaded files after a brief delay
    setTimeout(() => {
      setPendingFiles((prev) => prev.filter((f) => f.status !== "done"));
    }, 1500);

    await loadItems();
    setSending(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const hasText = text.trim().length > 0;
    const hasFiles = pendingFiles.some((f) => f.status === "queued" || f.status === "error");

    if (!hasText && !hasFiles) return;

    setSending(true);
    try {
      if (hasText) {
        await api.ingest.create(text, tags || undefined, project || undefined);
        setText("");
      }
      if (hasFiles) {
        await uploadAll();
      } else {
        await loadItems();
      }
      if (hasText && !hasFiles) {
        setTags("");
        setProject("");
      }
    } catch (err) {
      alert(`Failed to submit: ${err}`);
    }
    setSending(false);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      setIsDragging(false);
      dragCounter.current = 0;
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files);
      e.dataTransfer.clearData();
    }
  };

  const queuedCount = pendingFiles.filter((f) => f.status === "queued" || f.status === "error").length;

  return (
    <div
      className="max-w-4xl mx-auto p-6 relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="fixed inset-0 z-50 bg-m3-accent/10 backdrop-blur-sm border-4 border-dashed border-m3-accent flex items-center justify-center pointer-events-none">
          <div className="text-center">
            <div className="text-2xl font-bold text-m3-accent mb-2">Drop files to upload</div>
            <div className="text-sm text-m3-muted">Any number, any type</div>
          </div>
        </div>
      )}

      <h1 className="text-2xl font-bold mb-6">Inbox</h1>

      {/* Quick capture */}
      <form
        onSubmit={handleSubmit}
        className="mb-8 bg-m3-surface rounded-xl p-4 border border-m3-border"
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Share something with M3... (or drag files anywhere on this page)"
          className="w-full bg-transparent border-none outline-none resize-none text-m3-text placeholder-m3-muted mb-3"
          rows={3}
        />

        {/* Pending files list */}
        {pendingFiles.length > 0 && (
          <div className="mb-3 space-y-1.5">
            {pendingFiles.map((pf) => (
              <div
                key={pf.id}
                className="flex items-center gap-2 bg-m3-bg border border-m3-border rounded-lg px-3 py-2 text-sm"
              >
                <span className="flex-1 min-w-0 truncate">{pf.file.name}</span>
                <span className="text-xs text-m3-muted shrink-0">
                  {formatBytes(pf.file.size)}
                </span>
                {pf.status === "queued" && (
                  <span className="text-xs text-m3-muted shrink-0">queued</span>
                )}
                {pf.status === "uploading" && (
                  <span className="text-xs text-blue-400 shrink-0">uploading...</span>
                )}
                {pf.status === "done" && (
                  <span className="text-xs text-green-400 shrink-0">✓ sent</span>
                )}
                {pf.status === "error" && (
                  <span className="text-xs text-red-400 shrink-0" title={pf.error}>
                    failed
                  </span>
                )}
                {pf.status !== "uploading" && pf.status !== "done" && (
                  <button
                    type="button"
                    onClick={() => removeFile(pf.id)}
                    className="text-m3-muted hover:text-red-400 transition-colors shrink-0"
                    aria-label="Remove file"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

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
            multiple
            onChange={handleFileInput}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="px-3 py-1.5 bg-m3-bg border border-m3-border rounded-lg text-sm hover:bg-m3-border transition-colors"
          >
            Add files
          </button>
          <button
            type="submit"
            disabled={sending || (!text.trim() && queuedCount === 0)}
            className="px-4 py-1.5 bg-m3-accent text-white rounded-lg text-sm hover:bg-m3-accent-hover transition-colors disabled:opacity-50"
          >
            {sending
              ? "Sending..."
              : queuedCount > 0 && !text.trim()
                ? `Upload ${queuedCount}`
                : queuedCount > 0
                  ? `Send + ${queuedCount}`
                  : "Send"}
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
