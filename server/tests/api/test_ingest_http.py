from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[float(sum(t.encode()) % 256) / 256.0] * 768 for t in texts]


class _CannedLLM:
    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self, canned):
        self._canned = canned

    async def complete_tool(self, *, messages, tools, system, tool_choice, max_tokens, temperature):
        from m3.core.llm.base import ToolResult
        return ToolResult(tool_name=tool_choice, input=self._canned)


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    canned = {
        "kind": "personal",
        "interpretation": {"what_happened": "test note",
                           "when": {"iso": "2026-04-19", "source": "ingest_time"}, "confidence": 0.9},
        "open_questions": [], "hooks": {}, "self_updates": [], "entity_updates": [],
    }
    return build_app(brain_root=brain, embedder=_Embedder(), llm_factory=lambda: _CannedLLM(canned))


def test_ingest_text(app):
    client = TestClient(app)
    r = client.post("/api/v1/ingest/text", json={"text": "hello world", "source": "http"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "personal"
    assert body["confidence"] == 0.9
    assert "item_id" in body


def test_ingest_file_upload(app):
    client = TestClient(app)
    files = {"file": ("note.txt", b"coffee with Aditya", "text/plain")}
    data = {"source": "share_sheet"}
    r = client.post("/api/v1/ingest/file", files=files, data=data)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "personal"


def test_ingest_text_rejects_empty(app):
    client = TestClient(app)
    r = client.post("/api/v1/ingest/text", json={"text": ""})
    assert r.status_code == 422


def test_ingest_without_llm_factory_returns_503(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    app_no_llm = build_app(brain_root=brain, embedder=_Embedder())  # no llm_factory
    client = TestClient(app_no_llm)
    r = client.post("/api/v1/ingest/text", json={"text": "hi"})
    assert r.status_code == 503
