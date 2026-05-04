import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type CanvasResponse, type ChatCite } from "../api/client";
import ChatRail, { type MentionableEntity } from "../components/chat/ChatRail";
import Graph, { type GraphNode } from "../components/graph/Graph";
import NodeDetailCard from "../components/graph/NodeDetailCard";

export default function Workspace() {
  const [data, setData] = useState<CanvasResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState<boolean>(() =>
    typeof window === "undefined" ? true : window.matchMedia("(min-width: 768px)").matches,
  );

  const load = useCallback(async () => {
    try {
      const res = await api.canvas.get();
      setData(res);
      setError(null);
    } catch (err) {
      setError(`${err}`);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const mentionables: MentionableEntity[] = useMemo(() => {
    if (!data) return [];
    return data.nodes
      .filter((n) => n.node_type === "entity")
      .map((n) => ({
        // ChatRail expects bare entity uuids, not the "entity:" prefixed canvas id.
        id: n.id.startsWith("entity:") ? n.id.slice("entity:".length) : n.id,
        name: n.label,
        type: n.data.entity_type || "entity",
      }));
  }, [data]);

  const onCite = useCallback((c: ChatCite) => {
    setFocusedId(`entity:${c.entity_id}`);
  }, []);

  const onFocusEntity = useCallback((entityId: string) => {
    // ChatRail emits bare uuids; canvas nodes use the "entity:" prefix.
    setFocusedId(entityId.startsWith("entity:") ? entityId : `entity:${entityId}`);
  }, []);

  return (
    <div className="relative h-full w-full flex">
      <div className="relative flex-1 min-w-0">
        {error && (
          <div className="absolute inset-x-4 top-4 z-30 bg-red-900/30 border border-red-500/50 text-red-200 text-sm rounded px-3 py-2">
            Could not load graph: {error}
          </div>
        )}
        <Graph data={data} onNodeClick={setSelected} focusedId={focusedId} />
        {selected && (
          <NodeDetailCard
            node={selected}
            onClose={() => setSelected(null)}
          />
        )}
        <button
          className="absolute bottom-4 right-4 md:hidden bg-m3-accent text-white rounded-full w-12 h-12 shadow-lg flex items-center justify-center z-30"
          onClick={() => setChatOpen((v) => !v)}
          aria-label={chatOpen ? "Close chat" : "Open chat"}
        >
          {chatOpen ? "×" : "💬"}
        </button>
      </div>

      {chatOpen && (
        <div
          className="
            absolute md:static inset-x-0 bottom-0 md:inset-auto
            h-[60%] md:h-full md:w-[360px] lg:w-[400px]
            bg-m3-bg border-t md:border-t-0 md:border-l border-m3-border
            flex flex-col z-20
          "
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-m3-border md:hidden">
            <span className="text-sm font-semibold">Chat</span>
            <button
              onClick={() => setChatOpen(false)}
              className="text-m3-muted hover:text-m3-text"
              aria-label="Close chat"
            >
              ×
            </button>
          </div>
          <div className="flex-1 min-h-0">
            <ChatRail
              onCite={onCite}
              onThreadChanged={() => {}}
              onFocusEntity={onFocusEntity}
              mentionables={mentionables}
            />
          </div>
        </div>
      )}
    </div>
  );
}
