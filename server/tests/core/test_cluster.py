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
