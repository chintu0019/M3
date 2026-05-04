import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type ChatEvent = {
  type: string;
  content?: string;
  tool_name?: string;
  tool_input?: unknown;
  tool_result?: unknown;
};

export default function ChatMessage({ role, events, content }: {
  role: "user" | "assistant";
  events?: ChatEvent[];
  content?: string;
}) {
  if (role === "user") {
    return (
      <div className="mb-3 flex justify-end">
        <div className="max-w-[80%] px-4 py-2 rounded-2xl bg-m3-accent text-white">{content}</div>
      </div>
    );
  }
  return (
    <div className="mb-3">
      {events?.filter((e) => e.type === "tool_call").map((e, i) => (
        <div key={i} className="text-xs text-m3-muted mb-1">
          → {e.tool_name}({JSON.stringify(e.tool_input)})
        </div>
      ))}
      {content && (
        <div className="max-w-[80%] px-4 py-2 rounded-2xl bg-m3-surface border border-m3-border">
          <div className="text-sm leading-relaxed whitespace-pre-wrap">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
