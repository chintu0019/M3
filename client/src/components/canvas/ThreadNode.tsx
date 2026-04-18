import { Handle, Position } from "@xyflow/react";
import type { CanvasNodeData } from "../../api/client";

interface ThreadNodeProps {
  data: { label: string; data: CanvasNodeData };
}

export default function ThreadNode({ data: node }: ThreadNodeProps) {
  const { label, data } = node;
  const crystallized = !!data.crystallized_at;
  const ended = data.status === "ended";
  return (
    <div
      className={`canvas-node canvas-node--thread ${
        crystallized
          ? "canvas-node--thread-crystallized"
          : ended
          ? "canvas-node--thread-ended"
          : ""
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="canvas-node__meta">
        {crystallized
          ? "conversation · saved"
          : ended
          ? "conversation"
          : "conversation · live"}
      </div>
      <div className="canvas-node__title">{label}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
