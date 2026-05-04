from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.entity_doc import EntityDoc, upsert
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    return build_app(brain_root=brain, embedder=_Embedder())


def test_cluster_empty_query_returns_only_query_node(app):
    c = TestClient(app)
    r = c.get("/api/v1/cluster", params={"q": ""})
    assert r.status_code == 200
    body = r.json()
    assert len(body["nodes"]) >= 1
    assert any(n["type"] == "query" for n in body["nodes"])


def test_cluster_with_entities_returns_graph(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    upsert(brain, EntityDoc(
        canonical_name="Aditya", entity_type="person",
        aliases=[], description=None, related=[],
        signal_mentions=0, summary_external=None, body="",
    ))
    app = build_app(brain_root=brain, embedder=_Embedder())
    c = TestClient(app)
    r = c.get("/api/v1/cluster", params={"q": "Aditya"})
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body and "edges" in body
