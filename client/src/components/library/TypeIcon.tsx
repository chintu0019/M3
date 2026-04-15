const ICONS: Record<string, { icon: string; color: string }> = {
  pdf:   { icon: "📄", color: "text-red-400" },
  docx:  { icon: "📄", color: "text-blue-400" },
  xlsx:  { icon: "📊", color: "text-green-400" },
  pptx:  { icon: "📽", color: "text-orange-400" },
  epub:  { icon: "📖", color: "text-purple-400" },
  html:  { icon: "🌐", color: "text-cyan-400" },
  image: { icon: "🖼", color: "text-pink-400" },
  audio: { icon: "🎙", color: "text-yellow-400" },
  voice: { icon: "🎙", color: "text-yellow-400" },
  video: { icon: "🎬", color: "text-red-400" },
  url:   { icon: "🔗", color: "text-blue-400" },
  text:  { icon: "📝", color: "text-m3-muted" },
  file:  { icon: "📎", color: "text-m3-muted" },
};

export default function TypeIcon({ contentType }: { contentType: string | null }) {
  const meta = ICONS[contentType || "file"] || ICONS.file;
  return <span className={meta.color}>{meta.icon}</span>;
}
