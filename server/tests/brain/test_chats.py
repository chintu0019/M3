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


def test_read_meta_returns_defaults_when_sidecar_missing(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["id"] == sid
    assert meta["title"] == "hi"
    assert meta["title_locked"] is False
    assert meta["pinned"] is False
    assert meta["folder_id"] is None
    assert meta["created_at"]
    assert meta["updated_at"]


def test_write_meta_round_trip(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.write_meta(tmp_brain, sid, title="My title", pinned=True, folder_id="f_1")
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["title"] == "My title"
    assert meta["title_locked"] is True
    assert meta["pinned"] is True
    assert meta["folder_id"] == "f_1"


def test_write_meta_partial_update_preserves_other_fields(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.write_meta(tmp_brain, sid, title="First", pinned=True)
    _chats.write_meta(tmp_brain, sid, folder_id="f_2")
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["title"] == "First"
    assert meta["pinned"] is True
    assert meta["folder_id"] == "f_2"


def test_write_meta_explicit_lock_flag(tmp_brain: Path):
    """An auto-titler can write title without locking."""
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.write_meta(tmp_brain, sid, title="Auto", title_locked=False)
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["title"] == "Auto"
    assert meta["title_locked"] is False


def test_delete_session_removes_both_files(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    _chats.write_meta(tmp_brain, sid, title="X")
    _chats.delete_session(tmp_brain, sid)
    chats_dir = tmp_brain / "chats"
    assert not (chats_dir / f"{sid}.jsonl").exists()
    assert not (chats_dir / f"{sid}.meta.json").exists()


def test_delete_session_idempotent(tmp_brain: Path):
    _chats.delete_session(tmp_brain, "no-such-session")  # must not raise


def test_delete_session_meta_only(tmp_brain: Path):
    """Deleting a session that only has meta (orphaned sidecar) still cleans up."""
    chats_dir = tmp_brain / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / "orphan.meta.json").write_text("{}")
    _chats.delete_session(tmp_brain, "orphan")
    assert not (chats_dir / "orphan.meta.json").exists()


def test_read_meta_tolerates_non_dict_sidecar(tmp_brain: Path):
    """Corrupt sidecar containing valid JSON that isn't a dict shouldn't crash."""
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hi")
    meta_path = tmp_brain / "chats" / f"{sid}.meta.json"
    meta_path.write_text("[]")  # valid JSON, wrong shape
    meta = _chats.read_meta(tmp_brain, sid)
    assert meta["title"] == "hi"  # falls back to derived
    assert meta["pinned"] is False
