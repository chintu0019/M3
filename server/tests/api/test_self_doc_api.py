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
