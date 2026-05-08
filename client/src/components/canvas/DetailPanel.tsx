// Right-side detail panel: shows the full content of whichever node the
// user has focused on the canvas. Replaces the per-node hover-on-zoom card
// (which used to overlap unreadably whenever two nodes sat near each other)
// with a single, scrollable, dedicated surface.
//
// The panel is the *navigation primitive* now: clicking a node both opens
// the panel and highlights its 1-hop neighborhood on the canvas. From the
// panel the user can jump to a neighbor, which re-focuses without losing
// the "you, surrounded by your stuff" gestalt.

import type { ClusterNode } from "../../api/client";
import { CATEGORY_LABEL, catColor, deriveCategory } from "../../lib/canvasColors";

export interface DetailPanelProps {
  node: ClusterNode | null;
  /** Outgoing edges from `node`, paired with the matching cluster node so we
   *  can label and re-focus on a click. */
  neighbors: { node: ClusterNode; relation: string }[];
  onClose: () => void;
  onJumpTo: (id: string) => void;
}

export function DetailPanel({ node, neighbors, onClose, onJumpTo }: DetailPanelProps) {
  if (!node) return null;

  const cat = deriveCategory({
    type: node.type,
    entity_type: node.entity_type,
    kind: node.kind,
  });
  const accent = catColor(cat, 1);

  const heading = renderHeading(node);
  const body = renderBody(node);

  return (
    <aside className="m3-detail" aria-label="Node details">
      <header className="m3-detail__head">
        <span className="m3-detail__cat" style={{ color: accent, borderColor: accent }}>
          {CATEGORY_LABEL[cat] ?? node.type}
        </span>
        <button className="m3-detail__close" onClick={onClose} aria-label="Close detail">
          ✕
        </button>
      </header>

      <div className="m3-detail__title">{heading}</div>

      {body && <div className="m3-detail__body">{body}</div>}

      {neighbors.length > 0 && (
        <section className="m3-detail__neighbors">
          <div className="m3-detail__neighbors-label">Connected to</div>
          <ul>
            {neighbors.map(({ node: n, relation }) => {
              const ncat = deriveCategory({
                type: n.type, entity_type: n.entity_type, kind: n.kind,
              });
              return (
                <li key={n.id}>
                  <button onClick={() => onJumpTo(n.id)}>
                    <span className="m3-detail__neighbor-dot" style={{ background: catColor(ncat, 1) }} />
                    <span className="m3-detail__neighbor-label">{n.label || n.id}</span>
                    <span className="m3-detail__neighbor-rel">{relation}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </aside>
  );
}

function renderHeading(n: ClusterNode): string {
  if (n.type === "synthesis") {
    // The synthesis label is its truncated summary; the body renders the
    // full summary plus tensions, so the heading should be the entity name.
    return n.entity_slug ? humanizeSlug(n.entity_slug) : n.label;
  }
  return n.label || n.id;
}

function renderBody(n: ClusterNode): React.ReactNode {
  switch (n.type) {
    case "claim": {
      const conf = n.confidence != null ? Math.round(n.confidence * 100) : null;
      return (
        <>
          <p className="m3-detail__prose">{n.excerpt || n.label}</p>
          {conf != null && (
            <p className="m3-detail__meta">Confidence: {conf}%</p>
          )}
        </>
      );
    }
    case "synthesis":
      // excerpt holds the full summary; tensions are inside the body of the
      // markdown file but not exposed via the cluster node yet, so we show
      // just the summary here. (Future: surface tensions.)
      return <p className="m3-detail__prose">{n.excerpt || n.label}</p>;
    case "entity":
      return (
        <p className="m3-detail__meta">
          {n.entity_type ? `Type: ${n.entity_type}` : null}
        </p>
      );
    case "item":
      return n.excerpt ? (
        <pre className="m3-detail__quote">{n.excerpt}</pre>
      ) : null;
    case "query":
      return <p className="m3-detail__meta">This is you. Everything in M3 is your captured material.</p>;
    default:
      return null;
  }
}

function humanizeSlug(slug: string): string {
  return slug
    .split("-")
    .map(p => p ? p[0].toUpperCase() + p.slice(1) : p)
    .join(" ");
}
