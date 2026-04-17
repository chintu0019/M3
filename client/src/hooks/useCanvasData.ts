import { useCallback, useEffect, useRef, useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { api, CanvasLayoutUpdate, CanvasNode, CanvasEdge } from "../api/client";

function nodeKind(id: string): { node_type: string; node_id: string } {
  const idx = id.indexOf(":");
  return { node_type: id.slice(0, idx), node_id: id.slice(idx + 1) };
}

function toFlowNode(n: CanvasNode, fallbackIndex: number): Node {
  // Fan nodes without saved positions out in a rough grid.
  const cols = 10;
  const spacing = 220;
  const fallbackX = (fallbackIndex % cols) * spacing;
  const fallbackY = Math.floor(fallbackIndex / cols) * spacing;

  return {
    id: n.id,
    type: n.node_type,
    position: { x: n.x ?? fallbackX, y: n.y ?? fallbackY },
    data: { label: n.label, data: n.data },
  };
}

function toFlowEdge(e: CanvasEdge): Edge {
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    type: "default",
    data: { edge_type: e.edge_type, weight: e.weight },
    style: { strokeWidth: Math.min(3, 1 + e.weight * 0.3) },
  };
}

export function useCanvasData() {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.canvas.get();
      setNodes(res.nodes.map((n, i) => toFlowNode(n, i)));
      setEdges(res.edges.map(toFlowEdge));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pendingRef = useRef<Map<string, CanvasLayoutUpdate>>(new Map());
  const timerRef = useRef<number | null>(null);

  const flushLayout = useCallback(async () => {
    timerRef.current = null;
    const updates = Array.from(pendingRef.current.values());
    pendingRef.current.clear();
    if (!updates.length) return;
    try {
      await api.canvas.patchLayout(updates);
    } catch (err) {
      console.error("canvas layout flush failed", err);
    }
  }, []);

  const queueLayout = useCallback(
    (id: string, x: number, y: number) => {
      const { node_type, node_id } = nodeKind(id);
      pendingRef.current.set(id, { node_type, node_id, x, y });
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(flushLayout, 400);
    },
    [flushLayout],
  );

  return { nodes, edges, loading, error, reload: load, queueLayout, setNodes, setEdges };
}
