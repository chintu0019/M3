import { useCallback, useEffect, useRef, useState } from "react";
import { api, ChatCite } from "../../api/client";

export interface ChatDockProps {
  onCite: (c: ChatCite) => void;
  onThreadChanged: (threadId: string | null) => void;
}

interface LiveTurn {
  role: "user" | "assistant";
  content: string;
}

export default function ChatDock({ onCite, onThreadChanged }: ChatDockProps) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LiveTurn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [crystallizing, setCrystallizing] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const hasAssistantTurn = messages.some(
    (m) => m.role === "assistant" && m.content.trim().length > 0,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

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
    // Flip streaming and clear input synchronously so a fast second click
    // can't race through ensureThread() and create a duplicate thread.
    setStreaming(true);
    setInput("");
    try {
      const tid = await ensureThread();
      setMessages((m) => [
        ...m,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ]);
      for await (const event of api.chat(text, tid)) {
        if (event.text) {
          setMessages((m) => {
            const out = m.slice();
            const last = out[out.length - 1];
            if (last && last.role === "assistant") {
              out[out.length - 1] = { ...last, content: last.content + event.text };
            }
            return out;
          });
        }
        if (event.cite) {
          onCite(event.cite);
        }
      }
    } catch (err) {
      console.error("chat stream failed", err);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `⚠ stream error: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  async function endThread() {
    if (!threadId || crystallizing) return;
    setCrystallizing(true);
    try {
      if (hasAssistantTurn) {
        try {
          await api.threads.crystallize(threadId);
        } catch (err) {
          // Already-crystallized (409) or no assistant turn (400) — fall back to plain end.
          console.warn("crystallize failed, falling back to end", err);
          try {
            await api.threads.end(threadId);
          } catch (err2) {
            console.error("end thread failed", err2);
          }
        }
      } else {
        try {
          await api.threads.end(threadId);
        } catch (err) {
          console.error("end thread failed", err);
        }
      }
    } finally {
      setCrystallizing(false);
      setThreadId(null);
      setMessages([]);
      onThreadChanged(null);
    }
  }

  if (collapsed) {
    return (
      <button
        className="chat-dock chat-dock--collapsed"
        onClick={() => setCollapsed(false)}
        aria-label="Expand chat"
      >
        Chat
      </button>
    );
  }

  return (
    <div className="chat-dock" role="region" aria-label="Chat">
      <header className="chat-dock__header">
        <span className="chat-dock__title">
          {threadId ? "conversation" : "new conversation"}
        </span>
        <div className="chat-dock__actions">
          {threadId && (
            <button
              className="chat-dock__end"
              onClick={endThread}
              disabled={streaming || crystallizing}
            >
              {crystallizing ? "Saving…" : hasAssistantTurn ? "End & Save" : "End"}
            </button>
          )}
          <button
            className="chat-dock__collapse"
            onClick={() => setCollapsed(true)}
            aria-label="Collapse chat"
          >
            −
          </button>
        </div>
      </header>
      <div className="chat-dock__scroll" ref={scrollRef}>
        {messages.map((m, i) => (
          <div key={i} className={`chat-dock__turn chat-dock__turn--${m.role}`}>
            <span className="chat-dock__role">{m.role}</span>
            <span className="chat-dock__content">{m.content}</span>
          </div>
        ))}
      </div>
      <form
        className="chat-dock__input"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            crystallizing ? "Saving…" : streaming ? "Streaming…" : "Ask something…"
          }
          disabled={streaming || crystallizing}
        />
        <button
          type="submit"
          disabled={streaming || crystallizing || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}
