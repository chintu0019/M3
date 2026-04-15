import { type ItemDetail } from "../../api/client";

const IFRAME_TYPES = new Set(["pdf", "html"]);
const IMAGE_TYPES = new Set(["image"]);
const AUDIO_TYPES = new Set(["audio", "voice"]);
const VIDEO_TYPES = new Set(["video"]);

export default function FilePreview({ item }: { item: ItemDetail }) {
  const url = item.file_url;
  const type = item.content_type || "";

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

  // Unpreviewable types (docx, xlsx, pptx, etc.) -- fall through to extracted content
  return null;
}
