import { useEffect, useState } from "react";
import { api, ChatSessionSummary } from "../api/client";
import ChatMessage, { ChatEvent } from "../components/ChatMessage";

type Turn = { role: "user" | "assistant"; content: string; events?: ChatEvent[] };

export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sid, setSid] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [showPast, setShowPast] = useState(false);

  useEffect(() => {
    // Create a fresh session on mount so every new chat auto-persists.
    api.newChat()
      .then((r) => setSid(r.id))
      .catch(() => setSid(null));
    refreshSessions();
  }, []);

  async function refreshSessions() {
    try {
      const list = await api.listChats();
      setSessions(list);
    } catch {
      // Sidebar is nice-to-have; don't block chatting on it.
    }
  }

  async function startNewChat() {
    setTurns([]);
    try {
      const r = await api.newChat();
      setSid(r.id);
    } catch {
      setSid(null);
    }
    refreshSessions();
  }

  async function loadChat(sessionId: string) {
    try {
      const r = await api.getChat(sessionId);
      setSid(r.id);
      setTurns(
        r.turns.map((t) => ({
          role: t.role as "user" | "assistant",
          content: t.content,
          events: (t.events as ChatEvent[]) || [],
        })),
      );
      setShowPast(false);
    } catch {
      // ignore
    }
  }

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: text }, { role: "assistant", content: "", events: [] }]);
    setBusy(true);
    try {
      for await (const ev of api.chat(text, undefined, sid || undefined)) {
        const event = ev as ChatEvent;
        setTurns((t) => {
          const copy = t.slice();
          const last = copy[copy.length - 1];
          if (last.role !== "assistant") return copy;
          const events = [...(last.events || []), event];
          let content = last.content;
          if (event.type === "final") content = event.content || "";
          copy[copy.length - 1] = { ...last, events, content };
          return copy;
        });
      }
    } catch (e) {
      setTurns((t) => {
        const copy = t.slice();
        copy[copy.length - 1] = { role: "assistant", content: `error: ${e}` };
        return copy;
      });
    } finally {
      setBusy(false);
      refreshSessions();
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6 flex flex-col h-full">
      <div className="flex items-center justify-between mb-3 text-sm">
        <button
          onClick={() => setShowPast((s) => !s)}
          className="text-m3-muted hover:text-m3-text"
        >
          {showPast ? "Hide past chats" : `Past chats (${sessions.length})`}
        </button>
        <button
          onClick={startNewChat}
          className="text-m3-muted hover:text-m3-text"
        >
          New chat
        </button>
      </div>
      {showPast && (
        <div className="mb-3 border border-m3-border rounded-lg divide-y divide-m3-border max-h-64 overflow-auto">
          {sessions.length === 0 && (
            <div className="p-3 text-m3-muted text-sm">(no past chats)</div>
          )}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => loadChat(s.id)}
              className={`w-full text-left p-3 hover:bg-m3-surface ${s.id === sid ? "bg-m3-surface" : ""}`}
            >
              <div className="text-m3-text text-sm">{s.title}</div>
              <div className="text-m3-muted text-xs">
                {s.message_count} message{s.message_count === 1 ? "" : "s"} · {s.last_ts.slice(0, 10)}
              </div>
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-auto">
        {turns.length === 0 && (
          <div className="text-m3-muted text-sm">
            Ask something grounded in your brain: "Who did I meet last week?"
          </div>
        )}
        {turns.map((t, i) => (
          <ChatMessage key={i} role={t.role} events={t.events} content={t.content} />
        ))}
      </div>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask M3…"
          className="flex-1 bg-m3-surface border border-m3-border rounded-lg px-4 py-2 text-m3-text focus:outline-none focus:border-m3-accent"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="px-4 py-2 rounded-lg bg-m3-accent hover:bg-m3-accent-hover disabled:opacity-50"
        >
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
