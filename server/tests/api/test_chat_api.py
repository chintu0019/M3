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


class _CapturingLLM:
    """Records the system prompt it was called with so the test can assert
    the pinned-file block is present when scope_item_id is set."""
    supports_tools = True
    supports_vision = False
    supports_audio = False

    def __init__(self):
        self.last_system: str | None = None

    async def complete_tool(self, *, messages, tools, system, tool_choice, max_tokens, temperature):
        from m3.core.llm.base import ToolResult
        self.last_system = system
        return ToolResult(tool_name="", input={}, text="ok")


def test_chat_scope_item_id_injects_pinned_context(tmp_path):
    import uuid
    from m3.brain.items import ItemMeta, write_meta
    brain = tmp_path / "brain"
    init_brain(brain)
    item_id = uuid.UUID("77777777-7777-7777-7777-777777777777")
    write_meta(brain, ItemMeta(
        id=item_id, kind="reference", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename="recipe.md",
        extracted_text="To make pesto: blend basil, garlic, pine nuts, parmesan, olive oil.",
        when_iso=None, when_source="ingest_time", hooks={}, llm_output_raw={}, confidence=0.9,
    ))
    captured = _CapturingLLM()
    app = build_app(brain_root=brain, embedder=_Embedder(), llm_factory=lambda: captured)
    client = TestClient(app)
    with client.stream("POST", "/api/v1/chat", json={
        "message": "what's in this?", "scope_item_id": str(item_id),
    }) as r:
        # Drain the stream so the handler runs to completion.
        for _ in r.iter_lines():
            pass
        assert r.status_code == 200
    assert captured.last_system is not None
    assert "PINNED FILE CONTEXT" in captured.last_system
    assert str(item_id) in captured.last_system
    assert "pesto" in captured.last_system
