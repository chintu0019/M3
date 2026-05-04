"""Persist chat sessions as JSONL files under ~/brain/chats/<date>-<id>.jsonl.

One line per turn. Session id is a short uuid-prefixed date so filenames
sort chronologically. Files are append-only; nothing rewrites an old
session, so an interrupted chat is recoverable.
"""

from __future__ import annotations

import json
import uuid
from datetime import date as _date, datetime, timezone
from pathlib import Path


def _dir(root: Path) -> Path:
    d = root / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(root: Path, sid: str) -> Path:
    return _dir(root) / f"{sid}.jsonl"


def new_session(root: Path) -> str:
    """Create a fresh session id and empty file. Returns the id."""
    sid = f"{_date.today().isoformat()}-{uuid.uuid4().hex[:8]}"
    _session_path(root, sid).touch()
    return sid


def append_turn(
    root: Path,
    sid: str,
    role: str,
    content: str,
    events: list | None = None,
) -> None:
    line = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "content": content,
        "events": events or [],
    })
    with _session_path(root, sid).open("a") as fh:
        fh.write(line + "\n")


def load_session(root: Path, sid: str) -> list[dict]:
    p = _session_path(root, sid)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines rather than crash a load — partial
                # writes on unclean shutdown shouldn't brick a session.
                continue
    return out


def list_sessions(root: Path, *, limit: int = 20) -> list[dict]:
    """Return session summaries, newest first.

    Summary: {id, title, message_count, last_ts}. Empty sessions (no turns
    written yet) are skipped.
    """
    files = sorted(_dir(root).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict] = []
    for f in files[:limit]:
        sid = f.stem
        turns = load_session(root, sid)
        if not turns:
            continue
        # Title: first user message, truncated.
        title = "(empty)"
        for t in turns:
            if t.get("role") == "user":
                title = (t.get("content") or "")[:60]
                break
        out.append({
            "id": sid,
            "title": title,
            "message_count": len(turns),
            "last_ts": turns[-1]["ts"],
        })
    return out
