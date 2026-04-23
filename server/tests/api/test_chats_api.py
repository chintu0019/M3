from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain import chats as _chats
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    app = build_app(brain_root=brain, embedder=_Embedder())
    app.state._brain = brain   # expose for tests
    return app


def test_new_chat_returns_id(app):
    c = TestClient(app)
    r = c.post("/api/v1/chats")
    assert r.status_code == 200
    assert "id" in r.json()
    assert r.json()["id"]


def test_list_chats_empty(app):
    c = TestClient(app)
    r = c.get("/api/v1/chats")
    assert r.status_code == 200
    assert r.json() == []


def test_list_chats_after_ingest_shows_session(app):
    c = TestClient(app)
    r = c.post("/api/v1/chats")
    sid = r.json()["id"]
    # Put a turn on the session via the backend helper to avoid spinning up the LLM.
    _chats.append_turn(app.state._brain, sid, "user", "hello")
    listing = c.get("/api/v1/chats").json()
    assert len(listing) == 1
    assert listing[0]["id"] == sid
    assert listing[0]["title"] == "hello"


def test_get_missing_session_returns_404(app):
    c = TestClient(app)
    r = c.get("/api/v1/chats/does-not-exist")
    assert r.status_code == 404


def test_get_session_returns_turns(app):
    c = TestClient(app)
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "q")
    _chats.append_turn(app.state._brain, sid, "assistant", "a")
    r = c.get(f"/api/v1/chats/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    assert [t["role"] for t in body["turns"]] == ["user", "assistant"]
    assert [t["content"] for t in body["turns"]] == ["q", "a"]
