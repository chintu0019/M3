"""Build a fragment-rooted graph: query at the centre, items it matched around
it, and the entities those items hook to. Used by the /cluster retrieval
surface (C) and as a live-highlighting substrate for the chat agent panel.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from m3.brain.claims import claims_for_item, iter_claims
from m3.brain.entity_doc import load as load_entity
from m3.brain.entity_doc import slugify
from m3.brain.items import read_meta
from m3.brain.synthesis import iter_syntheses, read_synthesis
from m3.brain.topical import TopicalIndex
from m3.core.retrieve import Retriever


logger = logging.getLogger("m3.cluster")


NodeType = Literal["query", "item", "entity", "claim", "synthesis"]


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
    claim_id: str | None = None            # for claim nodes
    confidence: float | None = None        # for claim nodes
    synthesis_id: str | None = None        # for synthesis nodes
    topical_vec: list[float] | None = None  # 768-dim signature; populated from TopicalIndex


@dataclass
class ClusterEdge:
    source: str                            # node id
    target: str                            # node id
    kind: Literal["matched", "hooks", "related", "evidence", "synthesizes"]


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

        # Expand the item into its persisted claims so the canvas can lead with
        # propositions instead of raw text.
        try:
            item_uuid = _uuid.UUID(h.item_id)
        except (ValueError, TypeError):
            item_uuid = None
        if item_uuid is not None:
            for claim in claims_for_item(brain_root, item_uuid):
                claim_node_id = f"claim:{claim.id}"
                _add(ClusterNode(
                    id=claim_node_id, type="claim",
                    label=claim.proposition[:80],
                    excerpt=claim.proposition,
                    claim_id=str(claim.id), confidence=claim.confidence,
                ))
                graph.edges.append(ClusterEdge(
                    source=item_node_id, target=claim_node_id, kind="evidence",
                ))
                for slug in claim.entity_slugs:
                    entity_node_id = f"entity:{slug}"
                    if entity_node_id not in seen_nodes:
                        doc = load_entity(brain_root, slug=slug)
                        _add(ClusterNode(
                            id=entity_node_id, type="entity",
                            label=doc.canonical_name if doc else slug.replace("-", " "),
                            entity_type=doc.entity_type if doc else None,
                            entity_slug=slug,
                        ))
                    graph.edges.append(ClusterEdge(
                        source=claim_node_id, target=entity_node_id, kind="hooks",
                    ))

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

    # For every entity that ended up in the cluster, attach its synthesis (if
    # one exists) and an `synthesizes` edge from the synthesis to each of its
    # source claims that are also in the cluster. This is what makes the
    # canvas read as a wiki: distillations on top, propositions underneath,
    # raw items hidden by default.
    for node in list(graph.nodes):
        if node.type != "entity" or not node.entity_slug:
            continue
        synth = read_synthesis(brain_root, node.entity_slug)
        if synth is None:
            continue
        synth_node_id = f"synthesis:{node.entity_slug}"
        if synth_node_id not in seen_nodes:
            _add(ClusterNode(
                id=synth_node_id, type="synthesis",
                label=synth.summary[:80], excerpt=synth.summary,
                synthesis_id=str(synth.id), entity_slug=node.entity_slug,
            ))
        graph.edges.append(ClusterEdge(
            source=synth_node_id, target=node.id, kind="hooks",
        ))
        for cid in synth.claim_ids:
            claim_node_id = f"claim:{cid}"
            if claim_node_id in seen_nodes:
                graph.edges.append(ClusterEdge(
                    source=synth_node_id, target=claim_node_id, kind="synthesizes",
                ))

    _attach_topical_vecs(graph, brain_root)
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

    A self/"you" ego node is emitted at the center so the layout has a stable
    anchor; it carries no edges of its own — its presence alone is enough for
    the force layout to pin it center and orbit everything else around it.

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

    # Ego: a single "self" node anchors the canvas at center. Carries no
    # edges (would saturate fan-out into entities); the force layout pins
    # it on cat=="self" and orbits everything else around it.
    _add(ClusterNode(id="self", type="query", label="You"))

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

    # Claims + their evidence (item) and about (entity) edges.
    for claim in iter_claims(brain_root):
        claim_node_id = f"claim:{claim.id}"
        _add(ClusterNode(
            id=claim_node_id, type="claim",
            label=claim.proposition[:80],
            excerpt=claim.proposition,
            claim_id=str(claim.id), confidence=claim.confidence,
        ))
        item_node_id = f"item:{claim.item_id}"
        if item_node_id in seen:
            graph.edges.append(ClusterEdge(
                source=item_node_id, target=claim_node_id, kind="evidence",
            ))
        for slug in claim.entity_slugs:
            entity_node_id = f"entity:{slug}"
            if entity_node_id not in seen:
                # Stub the entity even if we don't have a dossier on disk.
                doc = load_entity(brain_root, slug=slug)
                _add(ClusterNode(
                    id=entity_node_id, type="entity",
                    label=doc.canonical_name if doc else slug.replace("-", " "),
                    entity_type=doc.entity_type if doc else None,
                    entity_slug=slug,
                ))
            graph.edges.append(ClusterEdge(
                source=claim_node_id, target=entity_node_id, kind="hooks",
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

    # Syntheses (one per entity at most). Attached to their entity by `hooks`
    # and to each contributing claim by `synthesizes` so the canvas can
    # foreground "this distillation, drawn from these atomic claims, is about
    # this entity."
    for synth in iter_syntheses(brain_root):
        entity_node_id = f"entity:{synth.entity_slug}"
        if entity_node_id not in seen:
            continue   # orphaned synthesis (shouldn't happen, but skip safely)
        synth_node_id = f"synthesis:{synth.entity_slug}"
        if synth_node_id not in seen:
            _add(ClusterNode(
                id=synth_node_id, type="synthesis",
                label=synth.summary[:80], excerpt=synth.summary,
                synthesis_id=str(synth.id), entity_slug=synth.entity_slug,
            ))
        graph.edges.append(ClusterEdge(
            source=synth_node_id, target=entity_node_id, kind="hooks",
        ))
        for cid in synth.claim_ids:
            claim_node_id = f"claim:{cid}"
            if claim_node_id in seen:
                graph.edges.append(ClusterEdge(
                    source=synth_node_id, target=claim_node_id, kind="synthesizes",
                ))

    _attach_topical_vecs(graph, brain_root)
    return graph


def _attach_topical_vecs(graph: ClusterGraph, brain_root: Path) -> None:
    """Populate node.topical_vec from the TopicalIndex in one bulk read.

    Best-effort: a corrupted or missing topical.sqlite degrades the
    canvas v2 layout to radial-only positioning rather than failing
    the cluster request.

    Note on response size: each topical_vec is 768 floats (~6KB
    serialized per node). For a brain with thousands of nodes this
    adds tens of MB to /cluster/all responses. Acceptable on
    localhost; revisit (float16 packing, opt-in flag, or binary
    encoding) if response size becomes a problem.
    """
    try:
        tidx = TopicalIndex.open(brain_root)
        try:
            vecs = {nid: v for nid, v in tidx.iter_all()}
        finally:
            tidx.close()
    except Exception:
        logger.warning(
            "topical_vec attach failed; canvas v2 layout will fall back to radial-only",
            exc_info=True,
        )
        return
    for node in graph.nodes:
        node.topical_vec = vecs.get(node.id)
