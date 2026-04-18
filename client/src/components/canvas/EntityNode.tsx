import { Handle, Position } from "@xyflow/react";
import { useEffect, useState } from "react";
import type { CanvasNodeData } from "../../api/client";

interface EntityNodeProps {
  data: { label: string; data: CanvasNodeData; _pulseAt?: number };
}

export default function EntityNode({ data: node }: EntityNodeProps) {
  const { label, data, _pulseAt } = node;
  const hasPage = !!data.has_page;
  const [pulse, setPulse] = useState(false);

  useEffect(() => {
    if (!_pulseAt) return;
    setPulse(true);
    const t = window.setTimeout(() => setPulse(false), 1200);
    return () => window.clearTimeout(t);
  }, [_pulseAt]);

  return (
    <div
      className={`canvas-node canvas-node--entity ${
        hasPage ? "canvas-node--page" : "canvas-node--chip"
      } ${pulse ? "canvas-node--pulse" : ""}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="canvas-node__title">{label}</div>
      {data.entity_type === "self" && (
        <div className="canvas-node__self-badge">self</div>
      )}
      {data.entity_type && data.entity_type !== "self" && (
        <div className="canvas-node__meta">{data.entity_type}</div>
      )}
      {hasPage && data.overview && (
        <div className="canvas-node__overview">{data.overview}</div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
