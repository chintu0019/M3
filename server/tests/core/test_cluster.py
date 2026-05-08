import uuid
from pathlib import Path

import pytest

from m3.brain.entity_doc import EntityDoc, upsert
from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import ItemMeta, write_meta
from m3.brain.vectors import VectorIndex
from m3.core.cluster import build_cluster


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[float(sum(t.encode()) % 256) / 256.0] * 768 for t in texts]


def _seed(tmp_brain, item_id, text, who=None, what=None):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID(item_id), kind="personal", source="cli",
        created_at="2026-04-23T10:00:00+00:00", original_filename=None,
        extracted_text=text, when_iso="2026-04-23", when_source="ingest_time",
        hooks={"who": who or [], "what": what or [], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.9,
    ))
    fts = FTSIndex.open(tmp_brain)
    fts.upsert_item(item_id=item_id, text=text)
    fts.close()
    hooks = HookIndex.open(tmp_brain)
    hooks.upsert_item_hooks(
        item_id=item_id,
        who=[h.get("name") for h in (who or []) if isinstance(h, dict)],
        what=[h.get("name") for h in (what or []) if isinstance(h, dict)],
        where=[], project=[], stance_entities=[],
    )
    hooks.close()
    vec = VectorIndex.open(tmp_brain)
    vec.upsert_item(item_id=item_id, embedding=[0.1] * 768)
    vec.close()


@pytest.mark.asyncio
async def test_build_cluster_includes_query_node_when_empty(tmp_brain: Path):
    graph = await build_cluster(brain_root=tmp_brain, embedder=_Embedder(), query="")
    assert any(n.type == "query" for n in graph.nodes)
    assert len(graph.edges) == 0


@pytest.mark.asyncio
async def test_build_cluster_connects_query_to_matched_items(tmp_brain: Path):
    _seed(tmp_brain, "00000000-0000-0000-0000-000000000001",
          "Coffee with Aditya about Pilot Path", who=[{"name": "Aditya"}])
    graph = await build_cluster(brain_root=tmp_brain, embedder=_Embedder(), query="Aditya")
    node_types = [n.type for n in graph.nodes]
    assert "query" in node_types
    assert "item" in node_types
    # query -> item edge exists
    assert any(e.source == "query" and e.kind == "matched" for e in graph.edges)


@pytest.mark.asyncio
async def test_build_cluster_walks_item_hooks_to_entities(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Aditya", entity_type="person", aliases=[], description=None,
        related=[], signal_mentions=0, summary_external=None, body="",
    ))
    _seed(tmp_brain, "00000000-0000-0000-0000-000000000002",
          "Met Aditya for coffee", who=[{"name": "Aditya"}])
    graph = await build_cluster(brain_root=tmp_brain, embedder=_Embedder(), query="Aditya")
    entities = [n for n in graph.nodes if n.type == "entity"]
    assert any(e.label == "Aditya" for e in entities)
    assert any(e.kind == "hooks" for e in graph.edges)


@pytest.mark.asyncio
async def test_build_cluster_walks_entity_related_edges(tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Pilot Path", entity_type="project", aliases=[], description=None,
        related=["aditya"], signal_mentions=0, summary_external=None, body="",
    ))
    upsert(tmp_brain, EntityDoc(
        canonical_name="Aditya", entity_type="person", aliases=[], description=None,
        related=[], signal_mentions=0, summary_external=None, body="",
    ))
    _seed(tmp_brain, "00000000-0000-0000-0000-000000000003",
          "Pilot Path planning", what=[{"name": "Pilot Path"}])
    graph = await build_cluster(brain_root=tmp_brain, embedder=_Embedder(), query="Pilot Path")
    # Both entities should appear, connected by a 'related' edge.
    slugs = {n.entity_slug for n in graph.nodes if n.type == "entity"}
    assert "pilot-path" in slugs
    assert "aditya" in slugs
    related_edges = [e for e in graph.edges if e.kind == "related"]
    assert len(related_edges) >= 1


@pytest.mark.asyncio
async def test_build_cluster_expands_items_into_their_claims(tmp_brain: Path):
    """When the retriever hits an item, its persisted claims should appear as
    'claim' nodes connected by 'evidence' edges. This is the Karpathy-style
    surface — propositions, not raw text."""
    from m3.brain.claims import ClaimMeta, write_claim

    item_id = "00000000-0000-0000-0000-0000000000aa"
    _seed(tmp_brain, item_id,
          "M3 stores everything as plain markdown for portability",
          what=[{"name": "M3"}])

    write_claim(tmp_brain, ClaimMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000c01"),
        item_id=uuid.UUID(item_id),
        proposition="M3 stores all data as plain markdown for portability.",
        confidence=0.9,
        supporting_span="stores everything as plain markdown",
        entity_slugs=["m3"],
        created_at="2026-05-01T10:00:00+00:00",
    ))

    graph = await build_cluster(brain_root=tmp_brain, embedder=_Embedder(), query="markdown")

    claim_nodes = [n for n in graph.nodes if n.type == "claim"]
    assert len(claim_nodes) == 1
    assert "plain markdown" in claim_nodes[0].label

    evidence_edges = [e for e in graph.edges if e.kind == "evidence"]
    assert len(evidence_edges) == 1
    assert evidence_edges[0].source == f"item:{item_id}"
    assert evidence_edges[0].target == f"claim:{claim_nodes[0].claim_id}"


@pytest.mark.asyncio
async def test_build_full_graph_surfaces_claims(tmp_brain: Path):
    from m3.brain.claims import ClaimMeta, write_claim
    from m3.core.cluster import build_full_graph

    item_id = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    _seed(tmp_brain, str(item_id), "Note about M3", what=[{"name": "M3"}])

    write_claim(tmp_brain, ClaimMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000c02"),
        item_id=item_id,
        proposition="M3 is a personal knowledge OS.",
        confidence=0.9, supporting_span="", entity_slugs=["m3"],
        created_at="2026-05-01T10:00:00+00:00",
    ))

    graph = await build_full_graph(brain_root=tmp_brain)
    claim_nodes = [n for n in graph.nodes if n.type == "claim"]
    assert len(claim_nodes) == 1

    # Claim should hook to its entity (m3) AND have an evidence edge from the item.
    assert any(e.kind == "evidence" and e.target.startswith("claim:") for e in graph.edges)
    assert any(e.kind == "hooks" and e.source.startswith("claim:") and e.target == "entity:m3"
               for e in graph.edges)


@pytest.mark.asyncio
async def test_build_full_graph_surfaces_synthesis_attached_to_entity(tmp_brain: Path):
    from m3.brain.claims import ClaimMeta, write_claim
    from m3.brain.synthesis import SynthesisMeta, write_synthesis
    from m3.core.cluster import build_full_graph

    item_id = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
    _seed(tmp_brain, str(item_id), "Note about M3", what=[{"name": "M3"}])

    upsert(tmp_brain, EntityDoc(
        canonical_name="M3", entity_type="project", aliases=[], description=None,
        related=[], signal_mentions=0, summary_external=None, body="",
    ))

    cid_a = uuid.UUID("00000000-0000-0000-0000-000000000c10")
    cid_b = uuid.UUID("00000000-0000-0000-0000-000000000c11")
    write_claim(tmp_brain, ClaimMeta(
        id=cid_a, item_id=item_id,
        proposition="M3 is local-first.", confidence=0.9, supporting_span="",
        entity_slugs=["m3"], created_at="2026-05-01T10:00:00+00:00",
    ))
    write_claim(tmp_brain, ClaimMeta(
        id=cid_b, item_id=item_id,
        proposition="M3 favors markdown.", confidence=0.9, supporting_span="",
        entity_slugs=["m3"], created_at="2026-05-01T10:00:00+00:00",
    ))

    write_synthesis(tmp_brain, SynthesisMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000d01"),
        entity_slug="m3",
        summary="M3 is a local-first markdown brain.",
        tensions=[],
        claim_ids=[cid_a, cid_b],
        generated_at="2026-05-08T10:00:00+00:00",
    ))

    graph = await build_full_graph(brain_root=tmp_brain)

    synth_nodes = [n for n in graph.nodes if n.type == "synthesis"]
    assert len(synth_nodes) == 1
    assert synth_nodes[0].entity_slug == "m3"

    # synthesis -> entity edge (hooks)
    assert any(
        e.kind == "hooks" and e.source.startswith("synthesis:") and e.target == "entity:m3"
        for e in graph.edges
    )
    # synthesis -> each contributing claim (synthesizes)
    synthesizes_edges = [e for e in graph.edges if e.kind == "synthesizes"]
    assert len(synthesizes_edges) == 2


@pytest.mark.asyncio
async def test_build_full_graph_emits_self_ego_node(tmp_brain: Path):
    """The at-rest canvas needs a single anchor — a 'You' node centered on
    the layout. Every full-graph response carries one regardless of what's
    in the brain."""
    from m3.core.cluster import build_full_graph
    graph = await build_full_graph(brain_root=tmp_brain)
    egos = [n for n in graph.nodes if n.type == "query"]
    assert len(egos) == 1
    assert egos[0].id == "self"
    assert egos[0].label == "You"
