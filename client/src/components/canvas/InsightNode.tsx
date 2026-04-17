import { Handle, Position } from "@xyflow/react";
import type { CanvasNodeData } from "../../api/client";

interface InsightNodeProps {
  data: { label: string; data: CanvasNodeData };
}

export default function InsightNode({ data: node }: InsightNodeProps) {
  const { label, data } = node;
  return (
    <div className="canvas-node canvas-node--insight">
      <Handle type="target" position={Position.Top} />
      <div className="canvas-node__title">* {label}</div>
      {data.insight_type && (
        <div className="canvas-node__meta">{data.insight_type}</div>
      )}
      {data.description && (
        <div className="canvas-node__overview">{data.description}</div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
