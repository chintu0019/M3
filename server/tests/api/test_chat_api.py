import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


class _FinalOnlyLLM:
    supports_tools = True
    supports_vision = False
    supports_audio = False
    async def complete_tool(self, *, messages, tools, system, tool_choice, max_tokens, temperature):
        from m3.core.llm.base import ToolResult
        return ToolResult(tool_name="", input={}, text="Hello from chat.")


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    return build_app(brain_root=brain, embedder=_Embedder(), llm_factory=lambda: _FinalOnlyLLM())


def test_chat_streams_events_and_final(app):
    client = TestClient(app)
    with client.stream("POST", "/api/v1/chat", json={"message": "hi"}) as r:
        assert r.status_code == 200
        events = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    continue
                events.append(json.loads(payload))
    assert any(e["type"] == "final" for e in events)
    final = next(e for e in events if e["type"] == "final")
    assert "Hello from chat" in final["content"]


def test_chat_requires_message(app):
    client = TestClient(app)
    r = client.post("/api/v1/chat", json={})
    assert r.status_code == 422
