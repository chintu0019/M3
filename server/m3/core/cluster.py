"""Build a fragment-rooted graph: query at the centre, items it matched around
it, and the entities those items hook to. Used by the /cluster retrieval
surface (C) and as a live-highlighting substrate for the chat agent panel.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from m3.brain.entity_doc import load as load_entity
from m3.brain.entity_doc import slugify
from m3.brain.items import read_meta
from m3.core.retrieve import Retriever


NodeType = Literal["query", "item", "entity"]


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ClusterNode:
    id: str                                # globally unique; prefixed per type
    type: NodeType
    label: str
    score: float = 0.0                     # retrieval score for items; 0 for entities
    kind: str | None = None                # item kind (personal/reference/record/signal/unknown)
    entity_type: str | None = None         # for entity nodes
    when_iso: str | None = None
    excerpt: str | None = None
    # Stable identifiers downstream consumers (chat highlighting) can match against.
    item_id: str | None = None
    entity_slug: str | None = None


@dataclass
class ClusterEdge:
    source: str                            # node id
    target: str                            # node id
    kind: Literal["matched", "hooks", "related"]


@dataclass
class ClusterGraph:
    nodes: list[ClusterNode] = field(default_factory=list)
    edges: list[ClusterEdge] = field(default_factory=list)


async def build_cluster(
    *, brain_root: Path, embedder: _Embedder, query: str, k: int = 15,
) -> ClusterGraph:
    """Run retrieval with the query, then expand each hit into its hooked entities
    and the entities' related neighbours. Returns a graph ready for d3-force."""
    retriever = Retriever(brain_root=brain_root, embedder=embedder)
    hits = await retriever.search(query, k=k)

    graph = ClusterGraph()
    seen_nodes: set[str] = set()

    def _add(node: ClusterNode) -> None:
        if node.id in seen_nodes:
            return
        seen_nodes.add(node.id)
        graph.nodes.append(node)

    # Query node at the centre. Empty query still makes a valid (lonely) graph.
    query_label = query.strip() or "(empty query)"
    _add(ClusterNode(id="query", type="query", label=query_label, score=1.0))

    # Items from retrieval
    for h in hits:
        item_node_id = f"item:{h.item_id}"
        _add(ClusterNode(
            id=item_node_id, type="item",
            label=(h.excerpt or h.snippet or h.item_id)[:60],
            score=h.score, kind=h.kind, when_iso=h.when_iso,
            excerpt=h.excerpt or h.snippet or "", item_id=h.item_id,
        ))
        graph.edges.append(ClusterEdge(source="query", target=item_node_id, kind="matched"))

        # Walk item hooks to add entity nodes
        try:
            meta = read_meta(brain_root, _uuid.UUID(h.item_id))
        except (ValueError, TypeError):
            meta = None
        if meta is None:
            continue
        hooks = meta.hooks or {}
        for hook_type in ("who", "what", "where"):
            for ref in hooks.get(hook_type) or []:
                name = _ref_name(ref)
                if not name:
                    continue
                slug = slugify(name)
                entity_node_id = f"entity:{slug}"
                # Prefer the stored entity's canonical name + type if available.
                entity_doc = load_entity(brain_root, slug=slug)
                label = entity_doc.canonical_name if entity_doc else name
                etype = entity_doc.entity_type if entity_doc else hook_type
                _add(ClusterNode(
                    id=entity_node_id, type="entity", label=label,
                    entity_type=etype, entity_slug=slug,
                ))
                graph.edges.append(ClusterEdge(source=item_node_id, target=entity_node_id, kind="hooks"))

                # Entity-to-entity related edges (one hop only)
                if entity_doc:
                    for related_slug in (entity_doc.related or []):
                        related_node_id = f"entity:{related_slug}"
                        if related_node_id not in seen_nodes:
                            related_doc = load_entity(brain_root, slug=related_slug)
                            if related_doc is None:
                                continue
                            _add(ClusterNode(
                                id=related_node_id, type="entity",
                                label=related_doc.canonical_name,
                                entity_type=related_doc.entity_type,
                                entity_slug=related_slug,
                            ))
                        # Undirected edge; keep source<target alphabetical so dedup works.
                        a, b = sorted([entity_node_id, related_node_id])
                        if not any(
                            e.source == a and e.target == b and e.kind == "related"
                            for e in graph.edges
                        ):
                            graph.edges.append(ClusterEdge(source=a, target=b, kind="related"))

    return graph


def _ref_name(ref) -> str:
    if isinstance(ref, dict):
        return (ref.get("name") or "").strip()
    if isinstance(ref, str):
        return ref.strip()
    return ""
