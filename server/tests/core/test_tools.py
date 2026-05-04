import asyncio
import uuid
from pathlib import Path

import pytest

from m3.brain.entity_doc import EntityDoc, upsert
from m3.brain.items import ItemMeta, write_item, write_meta
from m3.brain.questions import OpenQuestion, append as append_question
from m3.core.tools import BrainTools


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[float(sum(t.encode()) % 256) / 256.0] * 768 for t in texts]


@pytest.fixture
def tools(tmp_brain: Path):
    return BrainTools(brain_root=tmp_brain, embedder=_Embedder())


def _seed_item(brain: Path, item_id: str, text: str, who=None, what=None):
    meta = ItemMeta(
        id=uuid.UUID(item_id), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text=text, when_iso="2026-04-19", when_source="ingest_time",
        hooks={"who": who or [], "what": what or [], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.9,
    )
    write_meta(brain, meta)


@pytest.mark.asyncio
async def test_search_brain_returns_ranked_hits(tools, tmp_brain: Path):
    _seed_item(tmp_brain, "00000000-0000-0000-0000-000000000001", "Had coffee with Aditya.",
               who=[{"name": "Aditya"}])
    # Need to populate indexes too
    from m3.brain.reindex import reindex_all
    await reindex_all(tmp_brain, embedder=tools.embedder)

    hits = await tools.search_brain(query="Aditya", k=5)
    assert len(hits) == 1
    assert hits[0]["item_id"].endswith("000001")
    assert "reasons" in hits[0]


@pytest.mark.asyncio
async def test_open_item_returns_meta(tools, tmp_brain: Path):
    _seed_item(tmp_brain, "00000000-0000-0000-0000-000000000002", "Test note.")
    data = await tools.open_item(item_id="00000000-0000-0000-0000-000000000002")
    assert data["extracted_text"] == "Test note."
    assert data["kind"] == "personal"


@pytest.mark.asyncio
async def test_open_item_missing_returns_error(tools):
    data = await tools.open_item(item_id="00000000-0000-0000-0000-000000000999")
    assert "error" in data


@pytest.mark.asyncio
async def test_open_entity_returns_entity_and_items(tools, tmp_brain: Path):
    upsert(tmp_brain, EntityDoc(
        canonical_name="Aditya", entity_type="person",
        aliases=[], description="Coworker.", related=[],
        signal_mentions=0, summary_external=None, body="## Your history\n\n- Met yesterday.\n",
    ))
    _seed_item(tmp_brain, "00000000-0000-0000-0000-000000000003", "Coffee with Aditya.",
               who=[{"name": "Aditya"}])
    from m3.brain.reindex import reindex_all
    await reindex_all(tmp_brain, embedder=tools.embedder)

    data = await tools.open_entity(slug="aditya")
    assert data["canonical_name"] == "Aditya"
    assert "Met yesterday" in data["body"]
    assert "items" in data
    assert any(it["item_id"].endswith("000003") for it in data["items"])


@pytest.mark.asyncio
async def test_open_entity_missing_returns_error(tools):
    data = await tools.open_entity(slug="nope")
    assert "error" in data


@pytest.mark.asyncio
async def test_list_open_questions_returns_text_list(tools, tmp_brain: Path):
    append_question(tmp_brain, OpenQuestion(
        item_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
        question="Who is J?", context_snippet="call w/ J",
    ), created_date="2026-04-19")
    data = await tools.list_open_questions()
    assert len(data) == 1
    assert "Who is J?" in data[0]
