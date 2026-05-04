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
    upsert(brain, EntityDoc(
        canonical_name="Pilot Path", entity_type="company",
        aliases=["PilotPath"], description="Potential partner.",
        related=["aditya"], signal_mentions=0, summary_external=None,
        body="## Your context\n\n- Q2 partnership conversation.\n",
    ))
    upsert(brain, EntityDoc(
        canonical_name="Aditya", entity_type="person",
        aliases=[], description=None, related=["pilot-path"],
        signal_mentions=0, summary_external=None, body="",
    ))
    return build_app(brain_root=brain, embedder=_Embedder())


def test_list_entities(app):
    client = TestClient(app)
    r = client.get("/api/v1/entities")
    assert r.status_code == 200
    body = r.json()
    names = {e["canonical_name"] for e in body["entities"]}
    assert names == {"Pilot Path", "Aditya"}


def test_get_entity_by_slug(app):
    client = TestClient(app)
    r = client.get("/api/v1/entities/pilot-path")
    assert r.status_code == 200
    body = r.json()
    assert body["canonical_name"] == "Pilot Path"
    assert body["entity_type"] == "company"
    assert "Q2 partnership" in body["body"]
    assert "PilotPath" in body["aliases"]


def test_get_entity_missing_returns_404(app):
    client = TestClient(app)
    r = client.get("/api/v1/entities/nonexistent")
    assert r.status_code == 404
