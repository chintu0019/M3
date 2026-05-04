import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ChatSessionSummary, type ClusterResponse, type ClusterNode } from "../api/client";
import ChatMessage, { ChatEvent } from "../components/ChatMessage";
import ClusterGraph from "../components/ClusterGraph";

type Turn = { role: "user" | "assistant"; content: string; events?: ChatEvent[] };

// Server emits this when no LLM is configured. Carries the reason so the UI
// can show what's missing (no API key, claude CLI not installed, etc.) and
// link straight to Settings.
type UnconfiguredEvent = { type: "unconfigured"; reason: string };

export default function Chat() {
  const [sid, setSid] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [showPast, setShowPast] = useState(false);
  const [cluster, setCluster] = useState<ClusterResponse | null>(null);
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  // Set when the server emits an `unconfigured` SSE event for the most
  // recent turn. Renders an inline Settings CTA in place of the assistant
  // bubble's body so users don't see a generic error toast.
  const [unconfiguredReason, setUnconfiguredReason] = useState<string | null>(null);

  useEffect(() => {
    api.newChat()
      .then((r) => setSid(r.id))
      .catch(() => setSid(null));
    refreshSessions();
  }, []);

  async function refreshSessions() {
    try {
      setSessions(await api.listChats());
    } catch {
      // Sidebar is nice-to-have; don't block chatting on it.
    }
  }

  async function refreshCluster(q: string) {
    try {
      setCluster(await api.cluster(q));
    } catch {
      // Graph is nice-to-have; chat still works without it.
    }
  }

  function addHighlight(id: string) {
    setHighlightedIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }

  async function startNewChat() {
    setTurns([]);
    setCluster(null);
    setHighlightedIds(new Set());
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
      setHighlightedIds(new Set());
      setShowPast(false);
      // Seed the graph with the last user turn, if any.
      const lastUser = [...r.turns].reverse().find((t) => t.role === "user");
      if (lastUser) void refreshCluster(lastUser.content);
      else setCluster(null);
    } catch {
      // ignore
    }
  }

  async function submit() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setTurns((t) => [
      ...t,
      { role: "user", content: text },
      { role: "assistant", content: "", events: [] },
    ]);
    setBusy(true);
    setHighlightedIds(new Set());
    setUnconfiguredReason(null);
    // Refetch the cluster graph for this new turn, in parallel with the stream.
    void refreshCluster(text);

    try {
      for await (const ev of api.chat(text, undefined, sid || undefined)) {
        const event = ev as ChatEvent | UnconfiguredEvent;

        // Server says no LLM is wired up. Stop streaming, surface a CTA on
        // the in-flight assistant turn, and let the caller fix it in Settings.
        if (event.type === "unconfigured") {
          const reason = (event as UnconfiguredEvent).reason;
          setUnconfiguredReason(reason);
          setTurns((t) => {
            const copy = t.slice();
            copy[copy.length - 1] = {
              role: "assistant",
              content: "",
              events: [],
            };
            return copy;
          });
          break;
        }

        // Live highlight from agent tool events
        if (event.type === "tool_call") {
          const input = (event.tool_input as { item_id?: string; slug?: string }) || {};
          if (event.tool_name === "open_item" && input.item_id) {
            addHighlight(`item:${input.item_id}`);
          }
          if (event.tool_name === "open_entity" && input.slug) {
            addHighlight(`entity:${input.slug}`);
          }
        } else if (
          event.type === "tool_result" &&
          event.tool_name === "search_brain" &&
          Array.isArray(event.tool_result)
        ) {
          for (const hit of event.tool_result as Array<{ item_id?: string }>) {
            if (hit?.item_id) addHighlight(`item:${hit.item_id}`);
          }
        }

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
    <div className="h-full flex flex-col p-4">
      <div className="flex items-center justify-between mb-3 text-sm">
        <button
          onClick={() => setShowPast((s) => !s)}
          className="text-m3-muted hover:text-m3-text"
        >
          {showPast ? "Hide past chats" : `Past chats (${sessions.length})`}
        </button>
        <button onClick={startNewChat} className="text-m3-muted hover:text-m3-text">
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
              className={`w-full text-left p-3 hover:bg-m3-surface ${
                s.id === sid ? "bg-m3-surface" : ""
              }`}
            >
              <div className="text-m3-text text-sm">{s.title}</div>
              <div className="text-m3-muted text-xs">
                {s.message_count} message{s.message_count === 1 ? "" : "s"} ·{" "}
                {s.last_ts.slice(0, 10)}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Split pane: messages left, graph right. */}
      <div className="flex-1 grid grid-cols-5 gap-4 min-h-0">
        <div className="col-span-3 flex flex-col min-h-0">
          <div className="flex-1 overflow-auto pr-2">
            {turns.length === 0 && (
              <div className="text-m3-muted text-sm">
                Ask something grounded in your brain: "Who did I meet last week?"
              </div>
            )}
            {turns.map((t, i) => (
              <ChatMessage key={i} role={t.role} events={t.events} content={t.content} />
            ))}
            {unconfiguredReason && (
              <div className="mt-3 border border-yellow-600/50 bg-yellow-900/20 text-yellow-100 p-4 rounded">
                <div className="font-semibold mb-1">No AI agent configured</div>
                <div className="text-sm mb-3">{unconfiguredReason}</div>
                <Link
                  to="/settings"
                  className="inline-block px-3 py-1.5 rounded bg-yellow-600/30 hover:bg-yellow-600/50 text-yellow-50 text-sm"
                >
                  Open Settings
                </Link>
              </div>
            )}
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

        <div className="col-span-2 min-h-0 overflow-hidden">
          {cluster ? (
            <ClusterGraph
              nodes={cluster.nodes}
              edges={cluster.edges}
              highlightedIds={highlightedIds}
              onNodeClick={(n) => {
                const raw = n as ClusterNode;
                if (raw.type === "item" && raw.item_id) {
                  window.open(`/items/${raw.item_id}`, "_blank");
                } else if (raw.type === "entity" && raw.entity_slug) {
                  window.open(`/entities/${raw.entity_slug}`, "_blank");
                }
              }}
              height={600}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-m3-muted text-sm border border-m3-border rounded-lg">
              graph will appear after you send a message
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
