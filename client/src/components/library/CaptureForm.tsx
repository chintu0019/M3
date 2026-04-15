import { useRef, useState } from "react";
import { api } from "../../api/client";

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

export default function CaptureForm({ onAfterSend }: { onAfterSend: () => void }) {
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [project, setProject] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

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
    const toUpload = pendingFiles.filter((f) => f.status === "queued" || f.status === "error");
    await Promise.all(
      toUpload.map(async (pf) => {
        setPendingFiles((prev) => prev.map((f) => (f.id === pf.id ? { ...f, status: "uploading" } : f)));
        try {
          await api.ingest.upload(pf.file, tags || undefined, project || undefined);
          setPendingFiles((prev) => prev.map((f) => (f.id === pf.id ? { ...f, status: "done" } : f)));
        } catch (err) {
          setPendingFiles((prev) => prev.map((f) => (f.id === pf.id ? { ...f, status: "error", error: `${err}` } : f)));
        }
      }),
    );
    setTimeout(() => {
      setPendingFiles((prev) => prev.filter((f) => f.status !== "done"));
    }, 1500);
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
      if (hasFiles) await uploadAll();
      onAfterSend();
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
    if (e.target.files && e.target.files.length > 0) addFiles(e.target.files);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) setIsDragging(true);
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
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative"
    >
      {isDragging && (
        <div className="fixed inset-0 z-50 bg-m3-accent/10 backdrop-blur-sm border-4 border-dashed border-m3-accent flex items-center justify-center pointer-events-none">
          <div className="text-center">
            <div className="text-2xl font-bold text-m3-accent mb-2">Drop files to upload</div>
            <div className="text-sm text-m3-muted">Any number, any type</div>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-m3-surface rounded-xl p-4 border border-m3-border">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Share something with M3... (or drag files anywhere on this page)"
          className="w-full bg-transparent border-none outline-none resize-none text-m3-text placeholder-m3-muted mb-3"
          rows={2}
        />

        {pendingFiles.length > 0 && (
          <div className="mb-3 space-y-1.5">
            {pendingFiles.map((pf) => (
              <div key={pf.id} className="flex items-center gap-2 bg-m3-bg border border-m3-border rounded-lg px-3 py-2 text-sm">
                <span className="flex-1 min-w-0 truncate">{pf.file.name}</span>
                <span className="text-xs text-m3-muted shrink-0">{formatBytes(pf.file.size)}</span>
                {pf.status === "queued" && <span className="text-xs text-m3-muted shrink-0">queued</span>}
                {pf.status === "uploading" && <span className="text-xs text-blue-400 shrink-0">uploading...</span>}
                {pf.status === "done" && <span className="text-xs text-green-400 shrink-0">✓ sent</span>}
                {pf.status === "error" && <span className="text-xs text-red-400 shrink-0" title={pf.error}>failed</span>}
                {pf.status !== "uploading" && pf.status !== "done" && (
                  <button type="button" onClick={() => removeFile(pf.id)} className="text-m3-muted hover:text-red-400 transition-colors shrink-0">×</button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-3 items-center">
          <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Tags (comma-separated)" className="flex-1 bg-m3-bg border border-m3-border rounded-lg px-3 py-1.5 text-sm" />
          <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="Project" className="flex-1 bg-m3-bg border border-m3-border rounded-lg px-3 py-1.5 text-sm" />
          <input ref={fileRef} type="file" multiple onChange={handleFileInput} className="hidden" />
          <button type="button" onClick={() => fileRef.current?.click()} className="px-3 py-1.5 bg-m3-bg border border-m3-border rounded-lg text-sm hover:bg-m3-border transition-colors">Add files</button>
          <button type="submit" disabled={sending || (!text.trim() && queuedCount === 0)} className="px-4 py-1.5 bg-m3-accent text-white rounded-lg text-sm hover:bg-m3-accent-hover transition-colors disabled:opacity-50">
            {sending ? "Sending..." : queuedCount > 0 && !text.trim() ? `Upload ${queuedCount}` : queuedCount > 0 ? `Send + ${queuedCount}` : "Send"}
          </button>
        </div>
      </form>
    </div>
  );
}
