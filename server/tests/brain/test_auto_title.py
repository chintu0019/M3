from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from m3.brain import chats as _chats
from m3.brain.auto_title import generate_and_save_title


class _StubLLM:
    """Minimal LLMProvider-like stub: only `complete` is exercised."""
    def __init__(self, response: str = "Refactor force layout", raises: bool = False):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    async def complete(self, messages, system=None, max_tokens=4096, temperature=0.7):
        self.calls.append({"messages": messages, "system": system})
        if self.raises:
            raise RuntimeError("boom")
        return self.response


@pytest.mark.asyncio
async def test_generates_and_saves_title(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "Help me refactor force layout")
    _chats.append_turn(tmp_brain, sid, "assistant", "Sure, here's a plan...")
    llm = _StubLLM(response="Refactor force layout")
    await generate_and_save_title(tmp_brain, sid, llm)
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["title"] == "Refactor force layout"
    assert meta["title_locked"] is False  # auto-generated, user can override


@pytest.mark.asyncio
async def test_skips_when_title_is_locked(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.append_turn(tmp_brain, sid, "assistant", "hello")
    _chats.write_meta(tmp_brain, sid, title="User chose this")
    llm = _StubLLM()
    await generate_and_save_title(tmp_brain, sid, llm)
    assert _chats.read_meta(tmp_brain, sid)["title"] == "User chose this"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_failure_is_swallowed(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.append_turn(tmp_brain, sid, "assistant", "hello")
    llm = _StubLLM(raises=True)
    await generate_and_save_title(tmp_brain, sid, llm)  # must not raise
    # Title falls back to the derived first-user-message default.
    assert _chats.read_meta(tmp_brain, sid)["title"] == "hi"


@pytest.mark.asyncio
async def test_strips_quotes_and_truncates(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "q")
    _chats.append_turn(tmp_brain, sid, "assistant", "a")
    llm = _StubLLM(response='  "A very very very very very very very long title that must be cut" ')
    await generate_and_save_title(tmp_brain, sid, llm)
    meta = _chats.read_meta(tmp_brain, sid)
    assert not meta["title"].startswith('"')
    assert len(meta["title"]) <= 60


@pytest.mark.asyncio
async def test_skips_when_no_assistant_turn(tmp_brain: Path):
    """Pre-condition: must have at least one user + one assistant turn."""
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    llm = _StubLLM()
    await generate_and_save_title(tmp_brain, sid, llm)
    assert llm.calls == []
