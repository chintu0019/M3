// Compact chat panel scoped to a single uploaded file. Calls api.chat() with
// scope_item_id so the agent's search_brain only returns this file's hits and
// the file's text is pinned in the system prompt. Citations are rendered as
// inline chips, but they don't drive the canvas — the user is currently
// looking at one file, not the whole graph.

import { useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";

interface Turn {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
}

export interface FileChatProps {
  itemId: string;
  filename: string | null;
}

export function FileChat({ itemId, filename }: FileChatProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Reset the conversation whenever the user switches to a different file.
  useEffect(() => {
    setTurns([]);
    setStep(null);
    setStreaming(false);
  }, [itemId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns]);

  async function send(text: string) {
    if (!text.trim() || streaming) return;
    setInput("");
    setTurns(t => [
      ...t,
      { role: "user", text },
      { role: "assistant", text: "", streaming: true },
    ]);
    setStreaming(true);
    let final = "";
    try {
      for await (const ev of api.chat(text, { scope_item_id: itemId })) {
        if (ev.type === "tool_call") {
          setStep(describeTool(ev.tool_name, ev.tool_input));
        } else if (ev.type === "final") {
          final = ev.content || "";
          setStep(null);
        } else if (ev.type === "error") {
          final = `(error: ${ev.content || "unknown"})`;
          setStep(null);
        } else if (ev.type === "unconfigured") {
          final = `M3 has no AI agent configured. ${ev.reason || "Open Settings to pick one."}`;
          setStep(null);
        }
      }
    } catch (e) {
      final = `(network error: ${e instanceof Error ? e.message : String(e)})`;
    }
    setTurns(t => {
      const out = t.slice();
      out[out.length - 1] = { role: "assistant", text: final };
      return out;
    });
    setStreaming(false);
    setStep(null);
  }

  return (
    <div className="m3-file-chat">
      <div className="m3-file-chat__scope">
        Scoped to: <strong>{filename || "this file"}</strong>
      </div>
      <div className="m3-file-chat__scroll" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="m3-file-chat__empty">
            Ask anything about this file. The agent has its full text pinned in
            context and only retrieves from this item.
          </div>
        )}
        {turns.map((t, i) => (
          <div
            key={i}
            className={`m3-file-chat__turn m3-file-chat__turn--${t.role}`}
          >
            <div className="m3-file-chat__role">{t.role === "user" ? "You" : "M3"}</div>
            <div className="m3-file-chat__body">
              {renderWithCitations(t.text)}
              {t.streaming && step && (
                <div className="m3-file-chat__step">{step}</div>
              )}
            </div>
          </div>
        ))}
      </div>
      <form
        className="m3-file-chat__input"
        onSubmit={e => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about this file…"
          disabled={streaming}
        />
        <button type="submit" disabled={!input.trim() || streaming} aria-label="Send">
          Send
        </button>
      </form>
    </div>
  );
}

function describeTool(name: string | undefined, input: Record<string, unknown> | null | undefined): string {
  if (!name) return "Working";
  if (name === "search_brain") {
    const q = String((input?.query as string) ?? "").trim();
    return q ? `Searching for "${q.slice(0, 32)}"` : "Searching brain";
  }
  if (name === "open_item") return "Opening item";
  if (name === "open_entity") return "Reading entity";
  if (name === "list_open_questions") return "Listing open questions";
  return name.replace(/_/g, " ");
}

// Citations come back as `[^<item_id>]`. In the scoped panel the pinned item
// is the only possible source, so we render each marker as a small chip
// that links to the original file in a new tab.
function renderWithCitations(text: string): React.ReactNode[] {
  if (!text) return [];
  const parts: React.ReactNode[] = [];
  const re = /\[\^([a-zA-Z0-9-]+)\]/g;
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > last) parts.push(text.slice(last, idx));
    parts.push(
      <a
        key={`c${i++}`}
        className="m3-file-chat__cite"
        href={api.itemOriginalUrl(m[1])}
        target="_blank"
        rel="noreferrer"
        title={m[1]}
      >
        source
      </a>,
    );
    last = idx + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
