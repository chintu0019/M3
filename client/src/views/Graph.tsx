import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { drag as d3drag } from "d3-drag";
import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import { api, type EntityGraph } from "../api/client";

type SimNode = SimulationNodeDatum & {
  id: string;
  canonical_name: string;
  entity_type: string;
  fact_count: number;
  radius: number;
};
type SimLink = SimulationLinkDatum<SimNode> & {
  link_type: string;
  weight: number;
};

const TYPE_FILL: Record<string, string> = {
  person: "#34d399",
  project: "#818cf8",
  company: "#fbbf24",
  concept: "#38bdf8",
  place: "#fb7185",
  event: "#e879f9",
  topic: "#94a3b8",
};

function colorFor(type: string): string {
  return TYPE_FILL[type] ?? "#94a3b8";
}

export default function Graph() {
  const navigate = useNavigate();
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);

  const [data, setData] = useState<EntityGraph | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [zoomK, setZoomK] = useState(1);
  // Tick counter drives React re-render so positions flush; d3 mutates the
  // SimNode/SimLink objects in place, we just need React to notice.
  const [, forceTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (typeFilter) params.entity_type = typeFilter;
      setData(await api.entities.graph(params));
    } catch {
      setData(null);
    }
  }, [typeFilter]);
  useEffect(() => { load(); }, [load]);

  // Build stable sim arrays from the raw graph. d3 will mutate these during
  // the simulation — source/target strings become node object refs after
  // the link force initialises.
  const { simNodes, simLinks, types } = useMemo(() => {
    if (!data) return { simNodes: [] as SimNode[], simLinks: [] as SimLink[], types: [] as string[] };
    const simNodes: SimNode[] = data.nodes.map((n) => ({
      id: n.id,
      canonical_name: n.canonical_name,
      entity_type: n.entity_type,
      fact_count: n.fact_count,
      radius: Math.min(24, 6 + Math.sqrt(n.fact_count)),
    }));
    const nodeIds = new Set(simNodes.map((n) => n.id));
    const simLinks: SimLink[] = data.edges
      .filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id))
      .map((e) => ({
        source: e.source_id,
        target: e.target_id,
        link_type: e.link_type,
        weight: e.weight,
      }));
    const types = [...new Set(simNodes.map((n) => n.entity_type))].sort();
    return { simNodes, simLinks, types };
  }, [data]);

  // Run the simulation. d3 mutates simNodes/simLinks in place; we tick
  // setState to re-render with fresh positions.
  useEffect(() => {
    if (!svgRef.current) return;
    simRef.current?.stop();
    if (!simNodes.length) return;

    const { clientWidth: W, clientHeight: H } = svgRef.current;
    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance((l) => 80 + 40 / Math.max(1, l.weight))
          .strength(0.7),
      )
      .force("charge", forceManyBody<SimNode>().strength(-220))
      .force("center", forceCenter(W / 2, H / 2))
      .force(
        "collide",
        forceCollide<SimNode>().radius((d) => d.radius + 4),
      )
      .alphaDecay(0.04)
      .on("tick", () => forceTick((t) => t + 1));

    simRef.current = sim;
    return () => { sim.stop(); };
  }, [simNodes, simLinks]);

  // Zoom + pan. Bind once against the svg element; the root <g> carries
  // the resulting transform.
  useEffect(() => {
    if (!svgRef.current || !gRef.current) return;
    const svg = svgRef.current;
    const g = gRef.current;
    const zoomBehaviour = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.25, 4])
      .on("zoom", (event) => {
        const t: ZoomTransform = event.transform;
        g.setAttribute("transform", t.toString());
        setZoomK(t.k);
      });
    const sel = select(svg);
    sel.call(zoomBehaviour).call(zoomBehaviour.transform, zoomIdentity);
    return () => { sel.on(".zoom", null); };
  }, []);

  // Drag. Bind each rendered node group to a d3 drag handler once the
  // simulation exists. Matches by id via data-id attribute.
  useEffect(() => {
    if (!gRef.current || !simRef.current) return;
    const sim = simRef.current;
    const nodeSel = select(gRef.current).selectAll<SVGGElement, unknown>("g.node");
    const dragBehaviour = d3drag<SVGGElement, unknown>()
      .on("start", (event) => {
        const id = (event.sourceEvent.currentTarget as SVGGElement).getAttribute("data-id");
        if (!id) return;
        const node = simNodes.find((n) => n.id === id);
        if (!node) return;
        if (!event.active) sim.alphaTarget(0.3).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on("drag", (event) => {
        const id = (event.sourceEvent.currentTarget as SVGGElement).getAttribute("data-id");
        if (!id) return;
        const node = simNodes.find((n) => n.id === id);
        if (!node) return;
        node.fx = event.x;
        node.fy = event.y;
      })
      .on("end", (event) => {
        const id = (event.sourceEvent.currentTarget as SVGGElement).getAttribute("data-id");
        if (!id) return;
        const node = simNodes.find((n) => n.id === id);
        if (!node) return;
        if (!event.active) sim.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });
    nodeSel.call(dragBehaviour);
    return () => { nodeSel.on(".drag", null); };
  }, [simNodes]);

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]">
      <div className="flex items-center gap-4 p-3 border-b border-m3-border bg-m3-surface/40">
        <span className="text-sm font-medium">Entity Graph</span>
        <span className="text-xs text-m3-muted">
          {simNodes.length} nodes · {simLinks.length} edges · zoom {zoomK.toFixed(2)}x
        </span>
        <div className="flex gap-1">
          <button
            onClick={() => setTypeFilter(null)}
            className={`text-xs px-2 py-1 rounded border ${
              typeFilter === null
                ? "bg-m3-accent text-white border-m3-accent"
                : "text-m3-muted border-m3-border hover:text-m3-text"
            }`}
          >
            all
          </button>
          {types.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t === typeFilter ? null : t)}
              className={`text-xs px-2 py-1 rounded border ${
                typeFilter === t
                  ? "bg-m3-accent text-white border-m3-accent"
                  : "text-m3-muted border-m3-border hover:text-m3-text"
              }`}
            >
              <span
                className="inline-block w-2 h-2 rounded-full mr-1 align-middle"
                style={{ backgroundColor: colorFor(t) }}
              />
              {t}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <span className="text-xs text-m3-muted">drag to pan · scroll to zoom · drag a node to pin</span>
      </div>
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full select-none">
          <g ref={gRef}>
            <g className="links">
              {simLinks.map((l, idx) => {
                const s = l.source as SimNode | string;
                const t = l.target as SimNode | string;
                if (typeof s === "string" || typeof t === "string") return null;
                return (
                  <line
                    key={idx}
                    x1={s.x ?? 0}
                    y1={s.y ?? 0}
                    x2={t.x ?? 0}
                    y2={t.y ?? 0}
                    stroke="#334155"
                    strokeOpacity={0.6}
                    strokeWidth={Math.max(1, Math.min(5, Math.log2(1 + (l.weight || 1))))}
                  />
                );
              })}
            </g>
            <g className="nodes">
              {simNodes.map((n) => (
                <g
                  key={n.id}
                  data-id={n.id}
                  className="node cursor-pointer"
                  transform={`translate(${n.x ?? 0},${n.y ?? 0})`}
                  onClick={() => navigate(`/entities/${n.id}`)}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <circle
                    r={n.radius}
                    fill={colorFor(n.entity_type)}
                    fillOpacity={0.85}
                    stroke={hovered === n.id ? "#fff" : "#0f0f13"}
                    strokeWidth={hovered === n.id ? 2 : 1}
                  />
                  <text
                    y={n.radius + 12}
                    textAnchor="middle"
                    fontSize={10}
                    fill="#e4e4ef"
                    stroke="#0f0f13"
                    strokeWidth={3}
                    paintOrder="stroke"
                    pointerEvents="none"
                  >
                    {n.canonical_name}
                  </text>
                </g>
              ))}
            </g>
          </g>
        </svg>
        {simNodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-m3-muted text-sm">
            No entities yet. Share a note in wiki_mode=entity to populate.
          </div>
        )}
        {hovered && (() => {
          const h = simNodes.find((n) => n.id === hovered);
          if (!h) return null;
          return (
            <div className="absolute top-3 right-3 rounded-md border border-m3-border bg-m3-surface/90 backdrop-blur p-3 text-sm max-w-xs">
              <div className="font-medium">{h.canonical_name}</div>
              <div className="text-xs text-m3-muted">
                {h.entity_type} · {h.fact_count} facts
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
