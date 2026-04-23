import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ClusterResponse, type ClusterNode } from "../api/client";
import ClusterGraph from "../components/ClusterGraph";

export default function Cluster() {
  const [query, setQuery] = useState("");
  const [data, setData] = useState<ClusterResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ClusterNode | null>(null);

  useEffect(() => {
    const handle = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        setData(await api.cluster(query));
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }, 200);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="max-w-6xl mx-auto p-6">
      <input
        type="text"
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Browse by fragment — Sarah, Pacific, coffee…"
        className="w-full bg-m3-surface border border-m3-border rounded-lg px-4 py-3 text-m3-text placeholder-m3-muted focus:outline-none focus:border-m3-accent mb-4"
      />
      {loading && <div className="text-m3-muted text-sm mb-2">loading…</div>}
      {error && <div className="text-red-400 text-sm mb-2">{error}</div>}
      {data && (
        <div className="grid grid-cols-4 gap-4">
          <div className="col-span-3">
            <ClusterGraph
              nodes={data.nodes}
              edges={data.edges}
              onNodeClick={(n) => setSelected(n as ClusterNode)}
              height={560}
            />
          </div>
          <aside
            className="col-span-1 bg-m3-surface border border-m3-border rounded-lg p-4 overflow-auto"
            style={{ maxHeight: 560 }}
          >
            {selected ? (
              <NodeDetail node={selected} />
            ) : (
              <div className="text-m3-muted text-sm">
                click a node to see details
                <div className="mt-4 text-xs space-y-1">
                  <div>
                    {data.nodes.length} nodes · {data.edges.length} edges
                  </div>
                  <div>· center = query</div>
                  <div>· squares = items</div>
                  <div>· pills = entities</div>
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function NodeDetail({ node }: { node: ClusterNode }) {
  if (node.type === "item" && node.item_id) {
    return (
      <div className="text-sm">
        <div className="text-xs uppercase text-m3-muted mb-1">item · {node.kind}</div>
        <div className="mb-2">{node.label}</div>
        {node.excerpt && <div className="text-m3-muted mb-2">{node.excerpt}</div>}
        {node.when_iso && <div className="text-xs text-m3-muted">{node.when_iso}</div>}
        <Link
          to={`/items/${node.item_id}`}
          className="text-xs text-m3-accent hover:text-m3-accent-hover mt-2 inline-block"
        >
          open item →
        </Link>
      </div>
    );
  }
  if (node.type === "entity" && node.entity_slug) {
    return (
      <div className="text-sm">
        <div className="text-xs uppercase text-m3-muted mb-1">
          entity · {node.entity_type}
        </div>
        <div className="mb-2">{node.label}</div>
        <Link
          to={`/entities/${node.entity_slug}`}
          className="text-xs text-m3-accent hover:text-m3-accent-hover"
        >
          open entity →
        </Link>
      </div>
    );
  }
  return (
    <div className="text-sm">
      <div className="text-xs uppercase text-m3-muted mb-1">query</div>
      {node.label}
    </div>
  );
}
