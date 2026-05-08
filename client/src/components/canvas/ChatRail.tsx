// Left chat rail.
//
// Drives the live canvas via callbacks:
//   onTyping(text)      — pre-highlight nodes as the user types (parent does
//                         the substring match against current cluster nodes)
//   onSend(text)        — kick off a real chat round; we stream tokens here,
//                         then post-process the final text for [^id] markers
//                         and notify parent of each citation in order
//
// Citations: the agent loop emits `[^<item_id>]` inline. We split the final
// answer text on those markers, render each segment, and turn the marker
// into a numbered chip linked back to the canvas.

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import { catColor, type Category } from "../../lib/canvasColors";

export interface CitedRef {
  id: string;            // node id in the canvas (e.g. "item:<uuid>")
  itemId: string;        // raw item_id for fetching
  label: string;
  cat: Category;
}

export interface RailTurn {
  role: "user" | "assistant";
  text: string;          // for user turns this is the prompt; for assistant, the streaming answer
  cites: { itemId: string; offset: number }[];   // assistant only; offsets in `text`
  streaming?: boolean;
}

export interface ChatRailProps {
  onTyping: (text: string) => void;
  /** Fires once per chat turn at submit-time (before tokens stream).
   *  The canvas uses this to refetch the cluster so the graph reflects
   *  the current query. */
  onSend: (text: string) => void;
  onCitation: (citedRef: CitedRef) => void;
  resolveCitation: (itemId: string) => CitedRef | null;
  cited: CitedRef[];
  onCitedClick: (id: string) => void;
  onReset: () => void;
  /** Suggested prompts shown when there are no turns yet. */
  suggestions: string[];
  /** Currently active session id. Null = no session yet (mint on first send). */
  sessionId: string | null;
  /** Notify parent of session id changes (mint on first send, reset on "+"). */
  onSessionChange: (sid: string | null) => void;
  /** Bumps on every "new chat" trigger from the parent. Watched by the rail
   *  so that clicking "+" always feels responsive (clears draft, focuses
   *  input) even when sessionId was already null and React would otherwise
   *  short-circuit the state update. */
  newChatNonce?: number;
}

export function ChatRail({
  onTyping, onSend, onCitation, resolveCitation, cited, onCitedClick, onReset,
  suggestions, sessionId, onSessionChange, newChatNonce = 0,
}: ChatRailProps) {
  const [turns, setTurns] = useState<RailTurn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelRef = useRef({ cancelled: false });

  // Parent bumps newChatNonce on every "+" click. Always reset and focus the
  // input — even when sessionId was already null (in which case the
  // sessionId-driven effect would no-op). Skip on the initial mount; that's
  // covered by the sessionId effect below.
  const initialNonceRef = useRef(newChatNonce);
  useEffect(() => {
    if (newChatNonce === initialNonceRef.current) return;
    cancelRef.current.cancelled = true;
    setTurns([]);
    setInput("");
    setStreaming(false);
    setCurrentStep(null);
    if (sessionId !== null) onSessionChange(null);
    inputRef.current?.focus();
  }, [newChatNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns]);

  useEffect(() => { onTyping(input); }, [input, onTyping]);

  // Hydrate whenever the active session id changes. Each previous turn's text
  // + role gets converted into a RailTurn so the rail looks like the user left
  // it. Citations from prior turns aren't reconstructed (the SSE event log is
  // saved server-side but parsing it back into per-turn cite offsets isn't
  // worth the complexity) — they re-appear if the user re-asks.
  useEffect(() => {
    if (!sessionId) {
      setTurns([]);
      return;
    }
    let cancelled = false;
    api.getChat(sessionId)
      .then(res => {
        if (cancelled) return;
        const restored: RailTurn[] = res.turns.map(t => ({
          role: t.role === "user" ? "user" : "assistant",
          text: t.content,
          cites: [],
        }));
        setTurns(restored);
      })
      .catch(() => {
        if (cancelled) return;
        // Server doesn't have this session anymore (file deleted, fresh
        // brain, etc), tell the parent so it can drop the stale id.
        onSessionChange(null);
      });
    return () => { cancelled = true; };
  }, [sessionId, onSessionChange]);

  async function ensureSessionId(): Promise<string> {
    if (sessionId) return sessionId;
    const { id } = await api.newChat();
    onSessionChange(id);
    return id;
  }

  async function reset() {
    cancelRef.current.cancelled = true;
    setTurns([]);
    setInput("");
    setStreaming(false);
    setCurrentStep(null);
    if (sessionId !== null) onSessionChange(null);
    inputRef.current?.focus();
    onReset();
  }

  async function send(text: string) {
    if (!text.trim() || streaming) return;
    cancelRef.current = { cancelled: false };
    const cancel = cancelRef.current;
    setInput("");
    // Build history from already-completed turns BEFORE we add the new pair —
    // role/content shape matches what run_agent expects on the server.
    const history = turns.map(t => ({ role: t.role, content: t.text }));
    setTurns(t => [
      ...t,
      { role: "user", text, cites: [] },
      { role: "assistant", text: "", cites: [], streaming: true },
    ]);
    setStreaming(true);
    onSend(text);

    let finalText = "";
    let sid: string;
    try {
      sid = await ensureSessionId();
    } catch (e) {
      // Couldn't mint a session — fall through to a non-persistent send so
      // the user still gets a reply. Surface this in the assistant turn.
      finalText = `(could not create session: ${e instanceof Error ? e.message : String(e)})`;
      sid = "";
    }

    try {
      for await (const ev of api.chat(text, history, sid || undefined)) {
        if (cancel.cancelled) return;
        if (ev.type === "tool_call") {
          // Surface what the agent is doing right now. Each round can take
          // several seconds (esp. for subprocess-based agents like gemini),
          // so showing the current step turns dead-air "..." into "Searching
          // for X" / "Reading Y" — the wait reads as productive. We KEEP
          // this label after the matching tool_result fires (those events
          // arrive within milliseconds and React would otherwise batch them
          // into a single "Thinking" render, swallowing the meaningful
          // label entirely).
          setCurrentStep(describeToolCall(ev.tool_name ?? "", ev.tool_input ?? {}));
        } else if (ev.type === "tool_result") {
          // Intentionally a no-op for currentStep: the next tool_call (or
          // the final answer) will replace it.
        } else if (ev.type === "final") {
          finalText = ev.content || "";
          setCurrentStep(null);
        } else if (ev.type === "error") {
          finalText = `(error: ${ev.content || "unknown"})`;
          setCurrentStep(null);
        } else if (ev.type === "unconfigured") {
          finalText = `M3 has no AI agent configured. ${ev.reason || "Open Settings to pick one."}`;
          setCurrentStep(null);
        }
      }
    } catch (e) {
      finalText = `(network error: ${e instanceof Error ? e.message : String(e)})`;
      setCurrentStep(null);
    }

    if (cancel.cancelled) return;

    // Post-process for [^<item_id>] citations and stream the answer in
    // word-by-word, firing onCitation as each marker is "spoken". This gives
    // the canvas its pulse-and-fit choreography for free, even though the
    // backend gave us the full answer in one go.
    const { segments, ids } = parseCitations(finalText);
    setTurns(t => updateLast(t, last => ({ ...last, text: "", cites: [] })));

    for (let i = 0; i < segments.length; i++) {
      if (cancel.cancelled) return;
      const seg = segments[i];
      const words = seg.split(/(\s+)/);
      for (const w of words) {
        if (cancel.cancelled) return;
        await sleep(18 + Math.random() * 20);
        setTurns(t => updateLast(t, last => ({ ...last, text: last.text + w })));
      }
      const citeId = ids[i];
      if (citeId) {
        const ref = resolveCitation(citeId);
        if (ref) {
          setTurns(t =>
            updateLast(t, last => ({
              ...last,
              cites: [...last.cites, { itemId: citeId, offset: last.text.length }],
            })),
          );
          onCitation(ref);
          await sleep(380);
        }
      }
    }

    setTurns(t => updateLast(t, last => ({ ...last, streaming: false })));
    setStreaming(false);
    setCurrentStep(null);
  }

  return (
    <aside className="m3-chat-rail">
      <header className="m3-chat-rail__head">
        <div className="m3-chat-rail__title">
          <span className="m3-chat-rail__logo">M3</span>
          <span>Conversation</span>
        </div>
        <button className="m3-btn-ghost" onClick={reset} title="New conversation" aria-label="New conversation">
          <svg width="12" height="12" viewBox="0 0 16 16">
            <path d="M3 8h10M8 3v10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        </button>
      </header>

      <div className="m3-chat-rail__scroll" ref={scrollRef}>
        {turns.length === 0 && (
          <div className="m3-chat-rail__empty">
            <div className="m3-chat-rail__empty-label">Ask your knowledge base</div>
            <div className="m3-chat-rail__prompts">
              {suggestions.map(s => (
                <button key={s} className="m3-prompt-chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) => (
          <Turn key={i} turn={t} resolveCitation={resolveCitation} onCitedClick={onCitedClick} />
        ))}

        {streaming && turns.at(-1)?.text === "" && (
          <div className="m3-chat-rail__step">
            <span className="m3-chat-rail__streaming">
              <span className="m3-dot" /><span className="m3-dot" /><span className="m3-dot" />
            </span>
            <span className="m3-chat-rail__step-label">{currentStep ?? "Thinking"}</span>
          </div>
        )}
      </div>

      {cited.length > 0 && (
        <div className="m3-cited-panel">
          <div className="m3-cited-panel__title">Cited, in order</div>
          <ol className="m3-cited-list">
            {cited.map((c, i) => (
              <li key={c.id + i}>
                <button className="m3-cited-item" onClick={() => onCitedClick(c.id)}>
                  <span className="m3-cited-idx">{String(i + 1).padStart(2, "0")}</span>
                  <span className="m3-cited-dot" style={{ background: catColor(c.cat) }} />
                  <span className="m3-cited-name">{c.label}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      <form
        className="m3-chat-rail__input"
        onSubmit={e => { e.preventDefault(); send(input); }}
      >
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask your knowledge base…"
          disabled={streaming}
        />
        <button type="submit" disabled={!input.trim() || streaming} aria-label="Send">
          <svg width="14" height="14" viewBox="0 0 16 16">
            <path d="M2 8h11M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
    </aside>
  );
}

function Turn({
  turn, resolveCitation, onCitedClick,
}: {
  turn: RailTurn;
  resolveCitation: (id: string) => CitedRef | null;
  onCitedClick: (id: string) => void;
}) {
  const segments = useMemo(() => {
    if (turn.role === "user") return null;
    const parts: { text: string; itemId?: string }[] = [];
    let cursor = 0;
    for (const c of turn.cites) {
      if (c.offset > cursor) parts.push({ text: turn.text.slice(cursor, c.offset) });
      parts.push({ text: "", itemId: c.itemId });
      cursor = c.offset;
    }
    if (cursor < turn.text.length) parts.push({ text: turn.text.slice(cursor) });
    return parts;
  }, [turn]);

  if (turn.role === "user") {
    return (
      <div className="m3-turn m3-turn--user">
        <div className="m3-turn__role">You</div>
        <div className="m3-turn__body">{turn.text}</div>
      </div>
    );
  }

  return (
    <div className="m3-turn m3-turn--ai">
      <div className="m3-turn__role">M3</div>
      <div className="m3-turn__body">
        {segments?.map((p, i) => {
          if (p.itemId) {
            const ref = resolveCitation(p.itemId);
            if (!ref) return null;
            return (
              <button
                key={i}
                className="m3-cite"
                onClick={() => onCitedClick(ref.id)}
                style={{ borderBottomColor: catColor(ref.cat, 0.9) }}
                title={ref.label}
              >
                {ref.label.length > 28 ? ref.label.slice(0, 27) + "…" : ref.label}
              </button>
            );
          }
          return <span key={i}>{p.text}</span>;
        })}
      </div>
    </div>
  );
}

function updateLast(turns: RailTurn[], fn: (t: RailTurn) => RailTurn): RailTurn[] {
  if (turns.length === 0) return turns;
  const out = turns.slice();
  out[out.length - 1] = fn(out[out.length - 1]);
  return out;
}

function sleep(ms: number) {
  return new Promise(r => setTimeout(r, ms));
}

/**
 * Friendly label for the current agent step. Tool names are stable from
 * server/m3/core/tools.py — keep the cases in sync if new tools land.
 */
function describeToolCall(name: string, input: Record<string, unknown>): string {
  switch (name) {
    case "search_brain": {
      const q = String((input.query as string) ?? "").trim();
      return q ? `Searching for "${truncate(q, 32)}"` : "Searching brain";
    }
    case "open_item":
      return "Opening item";
    case "open_entity": {
      const slug = String((input.slug as string) ?? "").trim();
      return slug ? `Reading ${truncate(slug, 32)}` : "Reading entity";
    }
    case "list_open_questions":
      return "Listing open questions";
    default:
      return name ? name.replace(/_/g, " ") : "Working";
  }
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

/**
 * Split text on `[^<item_id>]` markers using matchAll. Returns an array of
 * plain segments and a parallel array of item_ids — `ids[i]` is the citation
 * that follows `segments[i]` (or undefined for the trailing segment).
 *
 *   "You decided X [^abc] and Y [^def]"
 *   → segments = ["You decided X ", " and Y ", ""]
 *     ids      = ["abc",            "def",     undefined]
 */
function parseCitations(text: string): { segments: string[]; ids: (string | undefined)[] } {
  const segments: string[] = [];
  const ids: (string | undefined)[] = [];
  let cursor = 0;
  for (const m of text.matchAll(/\[\^([a-zA-Z0-9-]+)\]/g)) {
    const start = m.index ?? 0;
    segments.push(text.slice(cursor, start));
    ids.push(m[1]);
    cursor = start + m[0].length;
  }
  segments.push(text.slice(cursor));
  ids.push(undefined);
  return { segments, ids };
}
