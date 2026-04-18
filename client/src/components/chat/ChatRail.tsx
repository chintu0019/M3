import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ChatCite } from "../../api/client";
import { entityColor } from "../canvas/graphStyle";

export interface MentionableEntity {
  id: string; // plain entity uuid, no "entity:" prefix
  name: string;
  type: string;
}

export interface ChatRailProps {
  onCite: (c: ChatCite) => void;
  onThreadChanged: (threadId: string | null) => void;
  onDraftChange?: (text: string) => void;
  onFocusEntity: (entityId: string) => void;
  /** Full entity list used for plain-text mention detection when the LLM
   * forgets the [[brackets]] format. Matched case-insensitively on word
   * boundaries. */
  mentionables: MentionableEntity[];
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
  mentionables,
}: ChatRailProps) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [crystallizing, setCrystallizing] = useState(false);
  const [cited, setCited] = useState<CitedEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Track which entity ids we've already emitted cites for in this turn so
  // the fallback scanner doesn't double-fire as more tokens arrive.
  const firedThisTurnRef = useRef<Set<string>>(new Set());

  // Sort mentionables by name length descending so the scanner matches the
  // longest possible entity first (e.g. "Dark mode" before "Dark").
  const mentionIndex = useMemo(() => {
    const out = mentionables
      .filter((m) => m.name && m.name.trim().length >= 3)
      .map((m) => ({
        id: m.id,
        name: m.name,
        type: m.type,
        // Escape regex metacharacters in the entity name so user-chosen
        // labels like "C++" or "Node.js" don't blow up the RegExp.
        re: new RegExp(
          `(?<![\\w])${m.name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}(?![\\w])`,
          "i",
        ),
      }));
    // Longer names first.
    out.sort((a, b) => b.name.length - a.name.length);
    return out;
  }, [mentionables]);

  function scanForMentions(text: string) {
    if (!mentionIndex.length) return;
    const fired = firedThisTurnRef.current;
    for (const m of mentionIndex) {
      if (fired.has(m.id)) continue;
      if (!m.re.test(text)) continue;
      fired.add(m.id);
      const c: ChatCite = { entity_id: m.id, name: m.name, entity_type: m.type };
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
    firedThisTurnRef.current = new Set();
    try {
      const tid = await ensureThread();
      setTurns((m) => [
        ...m,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ]);
      let accumulated = "";
      for await (const event of api.chat(text, tid)) {
        if (event.text) {
          accumulated += event.text;
          setTurns((m) => {
            const out = m.slice();
            const last = out[out.length - 1];
            if (last && last.role === "assistant") {
              out[out.length - 1] = { ...last, content: last.content + event.text };
            }
            return out;
          });
          // Fallback: detect entity names in plain streamed text when the LLM
          // skipped the [[brackets]] format. Genuine cite events from the
          // server still take precedence because they arrive via event.cite
          // and fill the same fired set first.
          scanForMentions(accumulated);
        }
        if (event.cite) {
          firedThisTurnRef.current.add(event.cite.entity_id);
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

  // Regex that highlights every canonical name as a clickable pill in the
  // assistant body, whether or not the model remembered to bracket it.
  const mentionRegex = useMemo(() => {
    const seen = new Set<string>();
    const parts: string[] = [];
    for (const m of mentionIndex) {
      const key = m.name.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      parts.push(m.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    }
    if (!parts.length) return null;
    return new RegExp(`(?<![\\w])(${parts.join("|")})(?![\\w])`, "gi");
  }, [mentionIndex]);

  const mentionableByKey = useMemo(() => {
    const m = new Map<string, MentionableEntity>();
    mentionIndex.forEach((e) =>
      m.set(e.name.toLowerCase().trim(), { id: e.id, name: e.name, type: e.type }),
    );
    return m;
  }, [mentionIndex]);

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
            mentionRegex={mentionRegex}
            mentionableByKey={mentionableByKey}
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
  mentionRegex: RegExp | null;
  mentionableByKey: Map<string, MentionableEntity>;
  onFocusEntity: (entityId: string) => void;
}

function ChatTurn({
  turn,
  citedByKey,
  mentionRegex,
  mentionableByKey,
  onFocusEntity,
}: ChatTurnProps) {
  if (turn.role === "user") {
    return (
      <div className="m3-turn m3-turn--user">
        <div className="m3-turn__role">You</div>
        <div className="m3-turn__body">{turn.content}</div>
      </div>
    );
  }

  const parts = renderWithCites(
    turn.content,
    citedByKey,
    mentionRegex,
    mentionableByKey,
    onFocusEntity,
  );
  return (
    <div className="m3-turn m3-turn--ai">
      <div className="m3-turn__role">M3</div>
      <div className="m3-turn__body">{parts}</div>
    </div>
  );
}

// Split an assistant turn's content into text runs and clickable cite pills.
// Two passes: strip [[Name]] markers (server-intended format), then scan any
// remaining text for canonical entity names so plain mentions also upgrade
// into pills when the model skips the brackets.
function renderWithCites(
  text: string,
  citedByKey: Map<string, CitedEntry>,
  mentionRegex: RegExp | null,
  mentionableByKey: Map<string, MentionableEntity>,
  onFocusEntity: (id: string) => void,
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let k = 0;

  const bracketRe = /\[\[([^\]]+)\]\]/g;
  let cursor = 0;
  let m: RegExpExecArray | null;
  while ((m = bracketRe.exec(text)) !== null) {
    if (m.index > cursor) {
      pushWithMentions(out, text.slice(cursor, m.index));
    }
    const name = m[1];
    const key = name.toLowerCase().trim();
    const cite = citedByKey.get(key);
    const mentionable = mentionableByKey.get(key);
    const resolved = cite ?? mentionable;
    if (resolved) {
      out.push(
        <button
          key={`c${k++}`}
          className="m3-cite"
          onClick={() => onFocusEntity(resolved.id)}
          style={{ borderBottomColor: entityColor(resolved.type, 0.9) }}
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
    pushWithMentions(out, text.slice(cursor));
  }
  return out;

  function pushWithMentions(dst: React.ReactNode[], chunk: string) {
    if (!mentionRegex || !chunk) {
      if (chunk) dst.push(<span key={`t${k++}`}>{chunk}</span>);
      return;
    }
    // RegExp.exec with /g needs lastIndex reset per scan.
    const local = new RegExp(mentionRegex.source, mentionRegex.flags);
    let c = 0;
    let mm: RegExpExecArray | null;
    while ((mm = local.exec(chunk)) !== null) {
      if (mm.index > c) {
        dst.push(<span key={`t${k++}`}>{chunk.slice(c, mm.index)}</span>);
      }
      const name = mm[1];
      const mentionable = mentionableByKey.get(name.toLowerCase().trim());
      if (mentionable) {
        dst.push(
          <button
            key={`m${k++}`}
            className="m3-cite"
            onClick={() => onFocusEntity(mentionable.id)}
            style={{ borderBottomColor: entityColor(mentionable.type, 0.9) }}
          >
            {name}
          </button>,
        );
      } else {
        dst.push(<span key={`u${k++}`}>{name}</span>);
      }
      c = mm.index + mm[0].length;
    }
    if (c < chunk.length) {
      dst.push(<span key={`t${k++}`}>{chunk.slice(c)}</span>);
    }
  }
}
