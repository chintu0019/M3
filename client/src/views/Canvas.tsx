import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  NodeChange,
  applyNodeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "../components/canvas/canvas.css";
import EntityNode from "../components/canvas/EntityNode";
import InsightNode from "../components/canvas/InsightNode";
import { useCanvasData } from "../hooks/useCanvasData";

export default function Canvas() {
  const { nodes, edges, loading, error, queueLayout, setNodes } = useCanvasData();

  const nodeTypes = useMemo(
    () => ({ entity: EntityNode, insight: InsightNode }),
    [],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((prev) => {
        const next = applyNodeChanges(changes, prev);
        for (const ch of changes) {
          if (ch.type === "position" && ch.position && !ch.dragging) {
            queueLayout(ch.id, ch.position.x, ch.position.y);
          }
        }
        return next;
      });
    },
    [queueLayout, setNodes],
  );

  if (loading && !nodes.length) {
    return <div className="p-6 text-m3-muted">Loading canvas…</div>;
  }
  if (error) {
    return <div className="p-6 text-red-500">Canvas error: {error}</div>;
  }

  return (
    <div className="canvas-surface">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        fitView
        minZoom={0.1}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={32} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}
