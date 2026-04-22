import { useState } from "react";
import { api } from "../api/client";
import ChatMessage, { ChatEvent } from "../components/ChatMessage";

type Turn = { role: "user" | "assistant"; content: string; events?: ChatEvent[] };

export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: text }, { role: "assistant", content: "", events: [] }]);
    setBusy(true);
    try {
      for await (const ev of api.chat(text)) {
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
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6 flex flex-col h-full">
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
