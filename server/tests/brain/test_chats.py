from __future__ import annotations

import time
from pathlib import Path

from m3.brain import chats as _chats


def test_new_session_creates_empty_file(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    assert _chats.load_session(tmp_brain, sid) == []


def test_append_and_load_roundtrip(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.append_turn(tmp_brain, sid, "assistant", "hello")
    turns = _chats.load_session(tmp_brain, sid)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["content"] == "hello"


def test_append_turn_preserves_events(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    events = [{"type": "tool_call", "tool_name": "search_brain"}]
    _chats.append_turn(tmp_brain, sid, "assistant", "answer", events=events)
    turns = _chats.load_session(tmp_brain, sid)
    assert turns[0]["events"] == events


def test_list_sessions_newest_first(tmp_brain: Path):
    sid_old = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid_old, "user", "first question")
    time.sleep(0.02)
    sid_new = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid_new, "user", "second question")
    sessions = _chats.list_sessions(tmp_brain)
    assert sessions[0]["id"] == sid_new
    assert sessions[0]["title"] == "second question"


def test_list_sessions_skips_empty(tmp_brain: Path):
    _chats.new_session(tmp_brain)  # empty
    populated = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, populated, "user", "hello")
    sessions = _chats.list_sessions(tmp_brain)
    assert len(sessions) == 1
    assert sessions[0]["id"] == populated


def test_list_sessions_title_truncates_long_content(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    long = "x" * 200
    _chats.append_turn(tmp_brain, sid, "user", long)
    sessions = _chats.list_sessions(tmp_brain)
    assert len(sessions[0]["title"]) == 60


def test_list_sessions_title_uses_first_user_message(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "assistant", "system-ish preamble")
    _chats.append_turn(tmp_brain, sid, "user", "the real question")
    sessions = _chats.list_sessions(tmp_brain)
    assert sessions[0]["title"] == "the real question"


def test_load_session_missing_returns_empty(tmp_brain: Path):
    assert _chats.load_session(tmp_brain, "nope") == []


def test_load_session_skips_malformed_lines(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "good")
    # Manually corrupt a line in the middle.
    p = tmp_brain / "chats" / f"{sid}.jsonl"
    p.write_text(p.read_text() + "garbage not json\n")
    _chats.append_turn(tmp_brain, sid, "assistant", "still works")
    turns = _chats.load_session(tmp_brain, sid)
    assert [t["content"] for t in turns] == ["good", "still works"]


def test_list_sessions_limit(tmp_brain: Path):
    for i in range(5):
        s = _chats.new_session(tmp_brain)
        _chats.append_turn(tmp_brain, s, "user", f"q{i}")
        time.sleep(0.01)
    sessions = _chats.list_sessions(tmp_brain, limit=3)
    assert len(sessions) == 3
