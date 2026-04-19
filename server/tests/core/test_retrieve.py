from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import ItemMeta, write_meta
from m3.brain.vectors import VectorIndex
from m3.core.retrieve import RetrievalHit, Retriever


def _write_item(tmp_brain: Path, item_id: str, text: str, who: list[str], when_iso: str):
    meta = ItemMeta(
        id=uuid.UUID(item_id),
        kind="personal",
        source="cli",
        created_at=f"{when_iso}T10:00:00+00:00",
        original_filename=None,
        extracted_text=text,
        when_iso=when_iso,
        when_source="ingest_time",
        hooks={"who": who, "what": [], "where": [], "project": [], "stance": []},
        llm_output_raw={},
        confidence=0.8,
    )
    write_meta(tmp_brain, meta)
    fts = FTSIndex.open(tmp_brain)
    fts.upsert_item(item_id=item_id, text=text)
    fts.close()
    hooks = HookIndex.open(tmp_brain)
    hooks.upsert_item_hooks(
        item_id=item_id, who=who, what=[], where=[], project=[], stance_entities=[]
    )
    hooks.close()
    vec = VectorIndex.open(tmp_brain)
    vec.upsert_item(item_id=item_id, embedding=[0.1] * 768)
    vec.close()


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.1] * 768 for _ in texts]


@pytest.mark.asyncio
async def test_keyword_match_returns_item_with_reason(tmp_brain: Path):
    _write_item(
        tmp_brain,
        "00000000-0000-0000-0000-000000000001",
        "Had coffee with Aditya.",
        ["Aditya"],
        "2026-04-19",
    )
    _write_item(
        tmp_brain,
        "00000000-0000-0000-0000-000000000002",
        "Receipt from Uber.",
        [],
        "2026-04-18",
    )
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("Aditya", k=5)
    assert len(hits) == 1
    assert hits[0].item_id.endswith("000001")
    assert any("who" in r or "keyword" in r for r in hits[0].reasons)


@pytest.mark.asyncio
async def test_ranking_combines_signals(tmp_brain: Path):
    # Item hit by keyword + hook should outrank item hit by keyword only.
    _write_item(
        tmp_brain,
        "00000000-0000-0000-0000-00000000aaaa",
        "About the Pacific project.",
        ["Aditya"],
        "2026-04-19",
    )
    _write_item(
        tmp_brain,
        "00000000-0000-0000-0000-00000000bbbb",
        "Randomly mentioned Aditya.",
        [],
        "2026-04-18",
    )
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("Aditya", k=5)
    ids = [h.item_id[-4:] for h in hits]
    assert ids[0] == "aaaa", f"expected aaaa (hook + keyword) first, got {ids}"


@pytest.mark.asyncio
async def test_empty_query_returns_empty(tmp_brain: Path):
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    assert await retriever.search("", k=5) == []


@pytest.mark.asyncio
async def test_hit_exposes_snippet_and_date(tmp_brain: Path):
    _write_item(
        tmp_brain,
        "00000000-0000-0000-0000-000000000010",
        "Had coffee with Aditya at the usual place.",
        ["Aditya"],
        "2026-04-17",
    )
    retriever = Retriever(brain_root=tmp_brain, embedder=_Embedder())
    hits = await retriever.search("coffee", k=5)
    assert len(hits) == 1
    assert hits[0].when_iso == "2026-04-17"
    assert "coffee" in hits[0].snippet.lower() or "coffee" in hits[0].excerpt.lower()


def test_retrieval_hit_is_dataclass():
    hit = RetrievalHit(
        item_id="x",
        score=1.0,
        kind="personal",
        when_iso=None,
        snippet="",
        excerpt="",
    )
    assert hit.reasons == []
