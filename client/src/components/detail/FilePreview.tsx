import { type ItemDetail } from "../../api/client";

const IFRAME_TYPES = new Set(["pdf", "html"]);
const IMAGE_TYPES = new Set(["image"]);
const AUDIO_TYPES = new Set(["audio", "voice"]);
const VIDEO_TYPES = new Set(["video"]);

function filename(path: string | null): string {
  if (!path) return "file";
  return path.split("/").pop() || path;
}

function FallbackCard({ item }: { item: ItemDetail }) {
  const url = item.file_url;
  if (!url) return null;
  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4 flex items-center gap-4">
      <span className="text-3xl">📎</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs uppercase tracking-wide text-m3-muted mb-1">Original file</div>
        <div className="text-sm font-medium truncate">{filename(item.file_path)}</div>
        <div className="text-xs text-m3-muted">
          {item.content_type || "file"} · preview not available in browser
        </div>
      </div>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm px-3 py-1.5 bg-m3-bg border border-m3-border rounded hover:border-m3-muted shrink-0"
      >
        ⬇ Download
      </a>
    </div>
  );
}

export default function FilePreview({ item }: { item: ItemDetail }) {
  const url = item.file_url;
  const type = item.content_type || "";

  // No file at all -- nothing to render. ExtractedContent shows the text below.
  if (!url) return null;

  if (IFRAME_TYPES.has(type)) {
    return (
      <div className="bg-m3-surface border border-m3-border rounded-xl overflow-hidden" style={{ height: 600 }}>
        <iframe src={url} className="w-full h-full" title="Preview" sandbox="allow-same-origin allow-scripts" />
      </div>
    );
  }
  if (IMAGE_TYPES.has(type)) {
    return (
      <div className="bg-m3-surface border border-m3-border rounded-xl p-4 flex items-center justify-center">
        <img src={url} alt={item.content_text || "image"} className="max-w-full max-h-[600px] object-contain rounded" />
      </div>
    );
  }
  if (AUDIO_TYPES.has(type)) {
    return (
      <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
        <audio src={url} controls className="w-full" />
      </div>
    );
  }
  if (VIDEO_TYPES.has(type)) {
    return (
      <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
        <video src={url} controls className="w-full max-h-[600px]" />
      </div>
    );
  }

  // Unpreviewable types (docx, xlsx, pptx, etc.) -- show a download card so the
  // user always knows the original file is there and can grab it.
  return <FallbackCard item={item} />;
}
