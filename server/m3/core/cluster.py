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


async def build_full_graph(*, brain_root: Path) -> ClusterGraph:
    """Return every item + every entity in the brain, with edges between them.
    Used as the canvas's "show me my whole brain" view — the chat then
    highlights subsets of this graph as citations stream in.

    Edges:
      - item ➜ entity   ("hooks")    — each item's resolved entity_updates
      - entity ➜ entity ("related")  — undirected, deduped, from entity.related
    """
    from m3.brain.layout import BrainPaths

    paths = BrainPaths(brain_root)
    graph = ClusterGraph()
    seen: set[str] = set()

    def _add(node: ClusterNode) -> None:
        if node.id in seen:
            return
        seen.add(node.id)
        graph.nodes.append(node)

    # Entities first so item->entity edges resolve cleanly.
    if paths.entities_dir.is_dir():
        for entity_file in sorted(paths.entities_dir.glob("*.md")):
            slug = entity_file.stem
            doc = load_entity(brain_root, slug=slug)
            if doc is None:
                continue
            _add(ClusterNode(
                id=f"entity:{slug}", type="entity",
                label=doc.canonical_name,
                entity_type=doc.entity_type,
                entity_slug=slug,
            ))

    # Items + their hooked entities.
    if paths.items_meta.is_dir():
        for meta_file in sorted(paths.items_meta.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                item_id = _uuid.UUID(meta_file.stem)
            except ValueError:
                continue
            meta = read_meta(brain_root, item_id)
            if meta is None:
                continue
            label = (meta.extracted_text or meta.original_filename or str(item_id))[:60]
            excerpt = (meta.extracted_text or "")[:280] or None
            _add(ClusterNode(
                id=f"item:{item_id}", type="item", label=label,
                kind=meta.kind, when_iso=meta.when_iso,
                excerpt=excerpt, item_id=str(item_id),
            ))
            # Link to entities mentioned in this item.
            updates = (meta.llm_output_raw or {}).get("entity_updates") or []
            for update in updates:
                if not isinstance(update, dict):
                    continue
                name = (update.get("canonical_name") or "").strip()
                if not name:
                    continue
                slug = slugify(name)
                entity_node_id = f"entity:{slug}"
                if entity_node_id not in seen:
                    # Stub the entity even if we don't have a dossier on disk.
                    _add(ClusterNode(
                        id=entity_node_id, type="entity", label=name,
                        entity_type=update.get("entity_type"),
                        entity_slug=slug,
                    ))
                graph.edges.append(ClusterEdge(
                    source=f"item:{item_id}", target=entity_node_id, kind="hooks",
                ))

    # Entity-entity related edges, deduped.
    related_seen: set[tuple[str, str]] = set()
    for node in list(graph.nodes):
        if node.type != "entity" or not node.entity_slug:
            continue
        doc = load_entity(brain_root, slug=node.entity_slug)
        if doc is None:
            continue
        for related_slug in doc.related or []:
            target = f"entity:{related_slug}"
            if target not in seen:
                continue
            a, b = sorted([node.id, target])
            if (a, b) in related_seen:
                continue
            related_seen.add((a, b))
            graph.edges.append(ClusterEdge(source=a, target=b, kind="related"))

    return graph
