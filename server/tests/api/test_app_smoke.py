import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[float(sum(t.encode()) % 256) / 256.0] * 768 for t in texts]


@pytest.fixture
def app_and_brain(tmp_path: Path, monkeypatch):
    brain = tmp_path / "brain"
    init_brain(brain)
    app = build_app(brain_root=brain, embedder=_Embedder())
    return app, brain


def test_root_returns_json_status(app_and_brain):
    app, _ = app_and_brain
    client = TestClient(app)
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "brain_root" in body


def test_retrieve_endpoint_wired(app_and_brain):
    app, _ = app_and_brain
    client = TestClient(app)
    r = client.get("/api/v1/retrieve", params={"q": ""})
    assert r.status_code == 200
    assert r.json() == {"hits": []}
