import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ChatCite } from "../../api/client";
import { entityColor } from "../canvas/graphStyle";

export interface ChatRailProps {
  onCite: (c: ChatCite) => void;
  onThreadChanged: (threadId: string | null) => void;
  onDraftChange?: (text: string) => void;
  onFocusEntity: (entityId: string) => void;
}

interface Turn {
  role: "user" | "assistant";
  content: string;
}

interface CitedEntry {
  id: string;
  name: string;
  type: string;
  key: string;
}

export default function ChatRail({
  onCite,
  onThreadChanged,
  onDraftChange,
  onFocusEntity,
}: ChatRailProps) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [crystallizing, setCrystallizing] = useState(false);
  const [cited, setCited] = useState<CitedEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const hasAssistantTurn = turns.some(
    (t) => t.role === "assistant" && t.content.trim().length > 0,
  );

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns]);

  const ensureThread = useCallback(async (): Promise<string> => {
    if (threadId) return threadId;
    const t = await api.threads.create();
    setThreadId(t.id);
    onThreadChanged(t.id);
    return t.id;
  }, [threadId, onThreadChanged]);

  async function send() {
    const text = input.trim();
    if (!text || streaming || crystallizing) return;
    setStreaming(true);
    setInput("");
    onDraftChange?.("");
    try {
      const tid = await ensureThread();
      setTurns((m) => [
        ...m,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ]);
      for await (const event of api.chat(text, tid)) {
        if (event.text) {
          setTurns((m) => {
            const out = m.slice();
            const last = out[out.length - 1];
            if (last && last.role === "assistant") {
              out[out.length - 1] = { ...last, content: last.content + event.text };
            }
            return out;
          });
        }
        if (event.cite) {
          const c: ChatCite = event.cite;
          setCited((prev) => {
            if (prev.some((p) => p.id === c.entity_id)) return prev;
            return [
              ...prev,
              {
                id: c.entity_id,
                name: c.name,
                type: c.entity_type,
                key: c.name.toLowerCase().trim(),
              },
            ];
          });
          onCite(c);
        }
      }
    } catch (err) {
      console.error("chat stream failed", err);
      setTurns((m) => [
        ...m,
        {
          role: "assistant",
          content: `\u26A0 stream error: ${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  async function reset() {
    if (streaming || crystallizing) return;
    if (threadId && hasAssistantTurn) {
      setCrystallizing(true);
      try {
        await api.threads.crystallize(threadId);
      } catch (err) {
        console.warn("crystallize failed, falling back to end", err);
        try {
          await api.threads.end(threadId);
        } catch (err2) {
          console.error("end thread failed", err2);
        }
      } finally {
        setCrystallizing(false);
      }
    } else if (threadId) {
      try {
        await api.threads.end(threadId);
      } catch (err) {
        console.error("end thread failed", err);
      }
    }
    setThreadId(null);
    setTurns([]);
    setCited([]);
    setInput("");
    onThreadChanged(null);
  }

  const citedByKey = useMemo(() => {
    const m = new Map<string, CitedEntry>();
    cited.forEach((c) => m.set(c.key, c));
    return m;
  }, [cited]);

  return (
    <aside className="m3-chat-rail">
      <header className="m3-chat-rail__head">
        <div className="m3-chat-rail__title">
          <span className="m3-chat-rail__logo">M3</span>
          <span>{threadId ? "conversation" : "new conversation"}</span>
        </div>
        <button
          className="m3-btn-ghost"
          onClick={() => void reset()}
          title={hasAssistantTurn ? "End & save conversation" : "New conversation"}
          disabled={streaming || crystallizing}
          aria-label="New conversation"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M3 8h10M8 3v10"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </header>

      <div className="m3-chat-rail__scroll" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="m3-chat-rail__empty">
            <div className="m3-chat-rail__empty-label">
              {crystallizing ? "Saving\u2026" : "Ask your knowledge base"}
            </div>
            <p className="m3-chat-rail__empty-hint">
              Mention an entity in the graph and the canvas will pulse it,
              pan to it, and draw the trail between consecutive citations.
            </p>
          </div>
        )}

        {turns.map((t, i) => (
          <ChatTurn
            key={i}
            turn={t}
            citedByKey={citedByKey}
            onFocusEntity={onFocusEntity}
          />
        ))}

        {streaming && (
          <div className="m3-chat-rail__streaming" aria-label="streaming">
            <span className="m3-dot" />
            <span className="m3-dot" />
            <span className="m3-dot" />
          </div>
        )}
      </div>

      {cited.length > 0 && (
        <div className="m3-cited-panel">
          <div className="m3-cited-panel__title">Cited, in order</div>
          <ol className="m3-cited-list">
            {cited.map((c, i) => (
              <li key={c.id}>
                <button
                  className="m3-cited-item"
                  onClick={() => onFocusEntity(c.id)}
                >
                  <span className="m3-cited-idx">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span
                    className="m3-cited-dot"
                    style={{ background: entityColor(c.type) }}
                  />
                  <span className="m3-cited-name">{c.name}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <form
        className="m3-chat-rail__input"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            onDraftChange?.(e.target.value);
          }}
          placeholder={
            crystallizing
              ? "Saving\u2026"
              : streaming
                ? "Streaming\u2026"
                : "Ask your knowledge base\u2026"
          }
          disabled={streaming || crystallizing}
        />
        <button
          type="submit"
          disabled={streaming || crystallizing || !input.trim()}
          aria-label="Send"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M2 8h11M9 4l4 4-4 4"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </aside>
  );
}

interface ChatTurnProps {
  turn: Turn;
  citedByKey: Map<string, CitedEntry>;
  onFocusEntity: (entityId: string) => void;
}

function ChatTurn({ turn, citedByKey, onFocusEntity }: ChatTurnProps) {
  if (turn.role === "user") {
    return (
      <div className="m3-turn m3-turn--user">
        <div className="m3-turn__role">You</div>
        <div className="m3-turn__body">{turn.content}</div>
      </div>
    );
  }

  const parts = renderWithCites(turn.content, citedByKey, onFocusEntity);
  return (
    <div className="m3-turn m3-turn--ai">
      <div className="m3-turn__role">M3</div>
      <div className="m3-turn__body">{parts}</div>
    </div>
  );
}

// Split an assistant turn's content into text runs and clickable [[Name]] pills.
// Server emits a parallel cite event with the resolved entity_id; we match back
// by lowercased name. If the cite hasn't streamed yet, render the raw name so
// prose stays readable and upgrades in place once it arrives.
function renderWithCites(
  text: string,
  citedByKey: Map<string, CitedEntry>,
  onFocusEntity: (id: string) => void,
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /\[\[([^\]]+)\]\]/g;
  let cursor = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > cursor) {
      out.push(<span key={`t${k++}`}>{text.slice(cursor, m.index)}</span>);
    }
    const name = m[1];
    const cite = citedByKey.get(name.toLowerCase().trim());
    if (cite) {
      out.push(
        <button
          key={`c${k++}`}
          className="m3-cite"
          onClick={() => onFocusEntity(cite.id)}
          style={{ borderBottomColor: entityColor(cite.type, 0.9) }}
        >
          {name}
        </button>,
      );
    } else {
      out.push(<span key={`u${k++}`}>{name}</span>);
    }
    cursor = m.index + m[0].length;
  }
  if (cursor < text.length) {
    out.push(<span key={`t${k++}`}>{text.slice(cursor)}</span>);
  }
  return out;
}
