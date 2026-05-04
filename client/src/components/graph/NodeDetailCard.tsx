import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../../api/client";
import type { GraphNode } from "./Graph";

interface Props {
  node: GraphNode;
  onClose: () => void;
}

const CITATION_RE = /\[\^([0-9a-fA-F-]{36})\]/g;

export default function NodeDetailCard({ node, onClose }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      setContent(null);
      try {
        const rawId = node.id.includes(":") ? node.id.split(":")[1] : node.id;
        if (node.nodeType === "entity") {
          const e = await api.entities.get(rawId);
          if (cancelled) return;
          setContent(
            e.page_content || e.page_overview || e.description || "_No wiki page yet for this entity._",
          );
        } else if (node.nodeType === "insight") {
          if (cancelled) return;
          setContent(node.description || "_No description provided._");
        } else {
          setContent("_Open the chat panel to revisit this thread._");
        }
      } catch (err) {
        if (!cancelled) setError(`${err}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [node.id, node.nodeType]);

  const transformed = content
    ? content.replace(CITATION_RE, (_m, uuid) => `[[source]](/documents/${uuid})`)
    : "";

  return (
    <aside className="absolute top-4 right-4 w-[min(380px,calc(100vw-32px))] max-h-[calc(100%-32px)] bg-m3-surface border border-m3-border rounded-xl shadow-xl overflow-hidden flex flex-col z-20">
      <header className="flex items-start justify-between gap-3 px-4 py-3 border-b border-m3-border">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-m3-muted">
            {node.entityType || node.insightType || node.nodeType}
          </div>
          <div className="font-semibold truncate">{node.name}</div>
        </div>
        <button
          onClick={onClose}
          className="text-m3-muted hover:text-m3-text shrink-0"
          aria-label="Close detail"
        >
          ×
        </button>
      </header>
      <div className="overflow-y-auto px-4 py-3 prose prose-invert prose-sm max-w-none">
        {loading && <div className="text-m3-muted text-sm">Loading…</div>}
        {error && <div className="text-red-400 text-sm">{error}</div>}
        {!loading && !error && (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children, ...rest }) => {
                if (href && href.startsWith("/documents/")) {
                  return (
                    <Link to={href} className="text-m3-accent underline" {...(rest as object)}>
                      {children}
                    </Link>
                  );
                }
                return (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-m3-accent underline"
                    {...rest}
                  >
                    {children}
                  </a>
                );
              },
            }}
          >
            {transformed}
          </ReactMarkdown>
        )}
      </div>
    </aside>
  );
}
