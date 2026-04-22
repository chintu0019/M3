import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.items import ItemMeta, write_item, write_meta
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    item_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    write_item(brain, item_id, extension="txt", content=b"hello world")
    write_meta(brain, ItemMeta(
        id=item_id, kind="personal", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename="hello.txt",
        extracted_text="hello world", when_iso="2026-04-19", when_source="ingest_time",
        hooks={}, llm_output_raw={}, confidence=0.8,
    ))
    return build_app(brain_root=brain, embedder=_Embedder())


def test_get_item_meta(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert body["extracted_text"] == "hello world"


def test_get_item_original_bytes(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/original")
    assert r.status_code == 200
    assert r.content == b"hello world"


def test_item_missing_returns_404(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert r.status_code == 404
