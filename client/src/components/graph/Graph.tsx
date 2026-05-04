import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { ForceGraphMethods } from "react-force-graph-2d";
import type { CanvasResponse } from "../../api/client";
import { entityColor, linkColor } from "../canvas/graphStyle";

export interface GraphNode {
  id: string;
  name: string;
  nodeType: "entity" | "insight" | "thread";
  entityType?: string;
  insightType?: string;
  description?: string;
  status?: string;
}

export interface GraphLink {
  source: string;
  target: string;
  type?: string;
}

interface Props {
  data: CanvasResponse | null;
  onNodeClick: (node: GraphNode) => void;
  focusedId: string | null;
}

function useResize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    });
    ro.observe(el);
    const rect = el.getBoundingClientRect();
    setSize({ width: rect.width, height: rect.height });
    return () => ro.disconnect();
  }, []);
  return { ref, size };
}

export default function Graph({ data, onNodeClick, focusedId }: Props) {
  const { ref, size } = useResize<HTMLDivElement>();
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined);

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodes: GraphNode[] = data.nodes.map((n) => ({
      id: n.id,
      name: n.label,
      nodeType: n.node_type,
      entityType: n.data.entity_type,
      insightType: n.data.insight_type,
      description: n.data.description,
      status: n.data.status,
    }));
    const ids = new Set(nodes.map((n) => n.id));
    const links: GraphLink[] = data.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, type: e.edge_type }));
    return { nodes, links };
  }, [data]);

  useEffect(() => {
    if (!focusedId || !fgRef.current) return;
    const node = graphData.nodes.find((n) => n.id === focusedId) as
      | (GraphNode & { x?: number; y?: number })
      | undefined;
    if (node && typeof node.x === "number" && typeof node.y === "number") {
      fgRef.current.centerAt(node.x, node.y, 600);
      fgRef.current.zoom(2.5, 600);
    }
  }, [focusedId, graphData.nodes]);

  const nodeColor = (n: GraphNode) => {
    if (n.nodeType === "insight") return "oklch(0.78 0.16 60 / 1)";
    if (n.nodeType === "thread") return "oklch(0.65 0.10 240 / 1)";
    return entityColor(n.entityType, 1);
  };

  return (
    <div ref={ref} className="w-full h-full bg-m3-bg">
      {size.width > 0 && size.height > 0 && (
        <ForceGraph2D<GraphNode, GraphLink>
          ref={fgRef}
          graphData={graphData}
          width={size.width}
          height={size.height}
          backgroundColor="transparent"
          nodeId="id"
          nodeLabel={(n: GraphNode) => `${n.name} (${n.entityType || n.insightType || n.nodeType})`}
          nodeRelSize={5}
          nodeColor={nodeColor}
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const n = node as GraphNode & { x?: number; y?: number };
            if (typeof n.x !== "number" || typeof n.y !== "number") return;
            const fontSize = Math.max(10 / globalScale, 2);
            if (globalScale < 0.6) return;
            ctx.font = `${fontSize}px sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = focusedId === n.id ? "#fff" : "rgba(220,220,230,0.85)";
            ctx.fillText(n.name, n.x, n.y + 8);
          }}
          linkColor={(l: GraphLink) => linkColor(l.type, 0.45)}
          linkWidth={(l: GraphLink) => (l.type === "contradicts" ? 1.5 : 0.6)}
          linkDirectionalParticles={0}
          cooldownTicks={120}
          onNodeClick={(n) => onNodeClick(n as GraphNode)}
          onNodeDragEnd={(n) => {
            const node = n as GraphNode & { x?: number; y?: number; fx?: number; fy?: number };
            node.fx = node.x;
            node.fy = node.y;
          }}
        />
      )}
    </div>
  );
}
