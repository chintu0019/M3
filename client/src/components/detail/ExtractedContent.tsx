import { useState } from "react";

export default function ExtractedContent({ content }: { content: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!content) return null;

  const short = content.length < 500;
  const display = expanded || short ? content : content.slice(0, 500) + "...";

  return (
    <div className="bg-m3-surface border border-m3-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase tracking-wide text-m3-muted">Extracted Content</div>
        <div className="text-xs text-m3-muted">{content.length.toLocaleString()} chars</div>
      </div>
      <pre className="whitespace-pre-wrap text-sm text-m3-text font-sans leading-relaxed">
        {display}
      </pre>
      {!short && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-xs text-m3-accent hover:text-m3-accent-hover"
        >
          {expanded ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}
