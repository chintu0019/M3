from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain
from m3.brain.self_doc import apply_update


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    apply_update(brain, slot="Preferences", operation="append",
                 new_content="- Likes ristretto", heading=None)
    return build_app(brain_root=brain, embedder=_Embedder())


def test_get_self_returns_all_slots(app):
    client = TestClient(app)
    r = client.get("/api/v1/self")
    assert r.status_code == 200
    body = r.json()
    assert "slots" in body
    assert "Preferences" in body["slots"]
    assert "Likes ristretto" in body["slots"]["Preferences"]
    assert set(body["slots"].keys()) == {
        "Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline",
    }


def test_put_self_slot_replaces_body(app):
    c = TestClient(app)
    r = c.put("/api/v1/self/Preferences", json={"slot": "Preferences", "new_content": "- like black coffee"})
    assert r.status_code == 200
    assert r.json()["new_body"] == "- like black coffee"
    body = c.get("/api/v1/self").json()
    assert "like black coffee" in body["slots"]["Preferences"]
    # Previous content should be gone
    assert "Likes ristretto" not in body["slots"]["Preferences"]


def test_put_self_slot_empty_clears(app):
    c = TestClient(app)
    c.put("/api/v1/self/Beliefs", json={"slot": "Beliefs", "new_content": "whatever"})
    r = c.put("/api/v1/self/Beliefs", json={"slot": "Beliefs", "new_content": ""})
    assert r.status_code == 200
    body = c.get("/api/v1/self").json()
    assert body["slots"]["Beliefs"].strip() in ("", "_(empty)_")


def test_put_unknown_slot_returns_404(app):
    c = TestClient(app)
    r = c.put("/api/v1/self/NotASlot", json={"slot": "NotASlot", "new_content": "x"})
    assert r.status_code == 404
