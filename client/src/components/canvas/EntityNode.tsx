import { Handle, Position } from "@xyflow/react";
import type { CanvasNodeData } from "../../api/client";

interface EntityNodeProps {
  data: { label: string; data: CanvasNodeData };
}

export default function EntityNode({ data: node }: EntityNodeProps) {
  const { label, data } = node;
  const hasPage = !!data.has_page;

  return (
    <div
      className={`canvas-node canvas-node--entity ${
        hasPage ? "canvas-node--page" : "canvas-node--chip"
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="canvas-node__title">{label}</div>
      {data.entity_type && (
        <div className="canvas-node__meta">{data.entity_type}</div>
      )}
      {hasPage && data.overview && (
        <div className="canvas-node__overview">{data.overview}</div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
