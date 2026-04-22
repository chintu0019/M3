"""Tests for the Telegram capture's M3ApiClient.

We bypass the python-telegram-bot Application entirely — TelegramCapture
creation needs a real bot token, which isn't available in CI. M3ApiClient
is the interesting bit: it talks to the local FastAPI app via httpx,
which we can wire to a FastAPI TestClient via its ASGITransport so no
actual network is involved.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain
from m3.capture.telegram import (
    M3ApiClient,
    _format_ingest_summary,
    _parse_allowed_chats,
    _truncate,
)


# --- pure helpers ---


def test_parse_allowed_chats_comma_separated():
    assert _parse_allowed_chats("123,456,789") == frozenset({123, 456, 789})


def test_parse_allowed_chats_handles_whitespace_and_empty():
    assert _parse_allowed_chats(" 1 ,, 2 ") == frozenset({1, 2})


def test_parse_allowed_chats_ignores_garbage():
    assert _parse_allowed_chats("1,not-an-int,2") == frozenset({1, 2})


def test_parse_allowed_chats_none_is_empty():
    assert _parse_allowed_chats(None) == frozenset()


def test_truncate_short_unchanged():
    assert _truncate("hello", 100) == "hello"


def test_truncate_long_gets_ellipsis():
    s = "x" * 100
    out = _truncate(s, 10)
    assert len(out) == 10
    assert out.endswith("…")


def test_format_ingest_summary_personal():
    out = _format_ingest_summary({
        "kind": "personal", "confidence": 0.87,
        "entities_touched": ["Aditya", "Pilot Path"],
        "questions_raised": 0,
    })
    assert "personal" in out
    assert "0.87" in out
    assert "Aditya" in out
    assert "Pilot Path" in out
    assert "open question" not in out


def test_format_ingest_summary_with_open_questions():
    out = _format_ingest_summary({
        "kind": "personal", "confidence": 0.4,
        "entities_touched": [], "questions_raised": 2,
    })
    assert "2 open questions" in out


def test_format_ingest_summary_singular_question():
    out = _format_ingest_summary({
        "kind": "personal", "confidence": 0.4,
        "entities_touched": [], "questions_raised": 1,
    })
    assert "1 open question" in out
    assert "questions" not in out  # no plural


# --- M3ApiClient against the real FastAPI app ---


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

    async def complete(self, *, messages, system=None, max_tokens=2048, temperature=0.2):
        return "canned final"


@pytest.fixture
def api_and_brain(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    canned_ingest = {
        "kind": "personal",
        "interpretation": {"what_happened": "tg text",
                           "when": {"iso": "2026-04-22", "source": "ingest_time"},
                           "confidence": 0.85},
        "open_questions": [], "hooks": {},
        "self_updates": [],
        "entity_updates": [],
    }
    app = build_app(
        brain_root=brain, embedder=_Embedder(),
        llm_factory=lambda: _CannedLLM(canned_ingest),
    )
    # Use httpx ASGITransport so M3ApiClient talks directly to the FastAPI app
    # over an in-memory transport. No real network, no need for TestClient lifespan.
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=60.0,
    )
    client = M3ApiClient(server_url="http://testserver", http_client=http)
    return client, brain


@pytest.mark.asyncio
async def test_api_client_ingest_text(api_and_brain):
    client, _ = api_and_brain
    out = await client.ingest_text("Had coffee with Aditya.")
    assert out["kind"] == "personal"
    assert "item_id" in out
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_ingest_file_roundtrips_as_text(api_and_brain):
    client, _ = api_and_brain
    out = await client.ingest_file(
        filename="note.txt", content=b"hello world", mime="text/plain",
    )
    assert out["kind"] == "personal"
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_status(api_and_brain):
    client, brain = api_and_brain
    out = await client.status()
    assert out["ok"] is True
    assert str(brain) in out["brain_root"]
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_retrieve_empty(api_and_brain):
    client, _ = api_and_brain
    hits = await client.retrieve("non-matching fragment")
    assert hits == []
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_retrieve_finds_ingested_text(api_and_brain):
    client, _ = api_and_brain
    await client.ingest_text("Met Sarah at the coffee place.")
    hits = await client.retrieve("Sarah", k=5)
    assert len(hits) >= 1
    assert any("Sarah" in (h.get("excerpt") or "") for h in hits)
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_entity_count(api_and_brain):
    client, _ = api_and_brain
    n = await client.entity_count()
    assert n == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_api_client_chat_returns_final(api_and_brain):
    client, _ = api_and_brain
    out = await client.chat("quick test")
    # The canned LLM's complete_tool echoes the same payload; the agent keeps calling
    # it and eventually hits the forced-final path which calls .complete() → "canned final"
    assert isinstance(out, str)
    assert len(out) > 0
    await client.aclose()
