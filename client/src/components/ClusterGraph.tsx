import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from "@xyflow/react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import "@xyflow/react/dist/style.css";

export interface ClusterNode {
  id: string;
  type: string; // "query" | "item" | "entity"
  label: string;
  score?: number;
  kind?: string | null;
  entity_type?: string | null;
  when_iso?: string | null;
  excerpt?: string | null;
  item_id?: string | null;
  entity_slug?: string | null;
}

export interface ClusterEdge {
  source: string;
  target: string;
  kind: string;
}

export interface ClusterGraphProps {
  nodes: ClusterNode[];
  edges: ClusterEdge[];
  highlightedIds?: Set<string>;
  onNodeClick?: (node: ClusterNode) => void;
  height?: number;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  type: string;
  label: string;
  raw: ClusterNode;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  kind: string;
}

const NODE_STYLES: Record<string, React.CSSProperties> = {
  query: {
    background: "#6366f1",
    color: "#fff",
    borderRadius: 8,
    border: "2px solid #818cf8",
    padding: "6px 10px",
    fontWeight: 700,
  },
  item: {
    background: "#1a1a24",
    color: "#e4e4ef",
    borderRadius: 4,
    border: "1px solid #2a2a3a",
    padding: "4px 8px",
    fontSize: 12,
  },
  entity: {
    background: "#2a2a3a",
    color: "#e4e4ef",
    borderRadius: 9999,
    border: "1px solid #3a3a4a",
    padding: "4px 10px",
    fontSize: 13,
  },
};

const HIGHLIGHT_STYLE: React.CSSProperties = {
  boxShadow: "0 0 0 3px #818cf8, 0 0 16px 4px rgba(129,140,248,0.5)",
};

function _runForce(nodes: SimNode[], links: SimLink[], width: number, height: number): void {
  const sim: Simulation<SimNode, SimLink> = forceSimulation(nodes)
    .force("charge", forceManyBody<SimNode>().strength(-220))
    .force(
      "link",
      forceLink<SimNode, SimLink>(links)
        .id((d) => d.id)
        .distance(110)
        .strength(0.3),
    )
    .force("center", forceCenter(width / 2, height / 2))
    .force("collide", forceCollide<SimNode>().radius(40))
    .force("x", forceX(width / 2).strength(0.04))
    .force("y", forceY(height / 2).strength(0.04))
    .stop();
  // Anchor the query node at centre so the layout pivots around it.
  const query = nodes.find((n) => n.type === "query");
  if (query) {
    query.fx = width / 2;
    query.fy = height / 2;
  }
  for (let i = 0; i < 250; i++) sim.tick();
}

export default function ClusterGraph({
  nodes,
  edges,
  highlightedIds,
  onNodeClick,
  height = 480,
}: ClusterGraphProps) {
  // The ReactFlow viewport pans/zooms; we just need a sane initial extent.
  const width = 720;

  const laidOut = useMemo(() => {
    const simNodes: SimNode[] = nodes.map((n) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      raw: n,
    }));
    const idSet = new Set(simNodes.map((s) => s.id));
    const simLinks: SimLink[] = edges
      .filter((e) => idSet.has(e.source) && idSet.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, kind: e.kind }));
    _runForce(simNodes, simLinks, width, height);
    return { simNodes, simLinks };
  }, [nodes, edges, height]);

  const rfNodes: Node[] = laidOut.simNodes.map((n) => {
    const base = NODE_STYLES[n.type] || NODE_STYLES.entity;
    const isHot = highlightedIds?.has(n.id);
    return {
      id: n.id,
      position: { x: n.x ?? 0, y: n.y ?? 0 },
      data: { label: n.label },
      style: {
        ...base,
        ...(isHot ? HIGHLIGHT_STYLE : {}),
        transition: "box-shadow 0.2s ease, transform 0.2s ease",
      },
      draggable: n.type !== "query",
    };
  });

  const rfEdges: Edge[] = laidOut.simLinks.map((e, i) => {
    const sourceId = typeof e.source === "string" ? e.source : (e.source as SimNode).id;
    const targetId = typeof e.target === "string" ? e.target : (e.target as SimNode).id;
    const hot = !!(highlightedIds?.has(sourceId) && highlightedIds?.has(targetId));
    return {
      id: `e${i}`,
      source: sourceId,
      target: targetId,
      style: {
        stroke: hot
          ? "#818cf8"
          : e.kind === "related"
            ? "#3a3a4a"
            : e.kind === "hooks"
              ? "#4a4a5a"
              : "#6366f1",
        strokeWidth: hot ? 2 : e.kind === "matched" ? 1.5 : 1,
        opacity: hot ? 1 : 0.7,
      },
      type: e.kind === "matched" ? "default" : "straight",
    };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Force remount when the node set changes so fitView recenters on each new
  // graph. xyflow v12's fitView only auto-fits on initial render, not when
  // the nodes array swaps wholesale.
  const graphKey = nodes.map((n) => n.id).join("|");

  return (
    <div
      style={{ width: "100%", height }}
      className="bg-m3-bg border border-m3-border rounded-lg overflow-hidden"
    >
      <ReactFlowProvider key={graphKey}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodeClick={(_, n) => {
            const raw = byId.get(n.id);
            if (raw && onNodeClick) onNodeClick(raw);
          }}
          fitView
          fitViewOptions={{ padding: 0.2, minZoom: 0.5, maxZoom: 2 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#2a2a3a" gap={24} />
          <Controls position="bottom-right" />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
