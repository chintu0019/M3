import uuid
from pathlib import Path

import pytest

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import ItemMeta, write_meta
from m3.brain.reindex import reindex_all


class _Embedder:
    """Deterministic per-text hash embedder (see tests/core/test_retrieve.py)."""

    dim = 768

    async def embed(self, texts):
        import hashlib

        out = []
        for t in texts:
            seed = hashlib.sha256(t.encode()).digest()
            vec: list[float] = []
            while len(vec) < 768:
                seed = hashlib.sha256(seed).digest()
                vec.extend(b / 255.0 for b in seed)
            out.append(vec[:768])
        return out


@pytest.mark.asyncio
async def test_reindex_populates_fts_and_hooks_from_existing_meta_files(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000abc"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="Had coffee with Aditya.", when_iso="2026-04-19", when_source="ingest_time",
        hooks={"who": [{"name": "Aditya"}], "what": [], "where": [], "project": [],
               "stance": []},
        llm_output_raw={}, confidence=0.8,
    ))
    result = await reindex_all(tmp_brain, embedder=_Embedder())
    assert result.items_indexed == 1
    fts = FTSIndex.open(tmp_brain)
    assert [h.id for h in fts.search("coffee", k=5)] == ["00000000-0000-0000-0000-000000000abc"]
    fts.close()
    hooks = HookIndex.open(tmp_brain)
    assert [h.item_id for h in hooks.search("aditya", types=["who"], k=5)] == ["00000000-0000-0000-0000-000000000abc"]
    hooks.close()


@pytest.mark.asyncio
async def test_reindex_is_idempotent(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-000000000abc"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="x", when_iso=None, when_source="unknown",
        hooks={"who": [], "what": [], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.0,
    ))
    await reindex_all(tmp_brain, embedder=_Embedder())
    await reindex_all(tmp_brain, embedder=_Embedder())
    fts = FTSIndex.open(tmp_brain)
    assert len(fts.search("x", k=10)) == 1
    fts.close()
