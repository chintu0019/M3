import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from m3.api.retrieve import build_retrieve_app
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


@pytest.fixture
def populated_brain(tmp_brain: Path):
    write_meta(tmp_brain, ItemMeta(
        id=uuid.UUID("00000000-0000-0000-0000-00000000cafe"), kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename=None,
        extracted_text="Had coffee with Aditya about Pacific.",
        when_iso="2026-04-19", when_source="ingest_time",
        hooks={"who": [{"name": "Aditya"}], "what": [{"name": "Pacific"}], "where": [], "project": [], "stance": []},
        llm_output_raw={}, confidence=0.9,
    ))
    import asyncio
    asyncio.run(reindex_all(tmp_brain, embedder=_Embedder()))
    return tmp_brain


def test_retrieve_endpoint_returns_ranked_hits(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": "coffee"})
    assert r.status_code == 200
    body = r.json()
    assert "hits" in body
    assert len(body["hits"]) >= 1
    assert body["hits"][0]["item_id"].endswith("cafe")
    assert "reasons" in body["hits"][0]


def test_retrieve_empty_query_returns_empty_hits(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_retrieve_k_param_limits_results(populated_brain: Path):
    app = build_retrieve_app(brain_root=populated_brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": "Aditya", "k": 1})
    assert r.status_code == 200
    assert len(r.json()["hits"]) <= 1
