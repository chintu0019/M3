"""Persist chat sessions as JSONL files under ~/brain/chats/<date>-<id>.jsonl.

One line per turn. Session id is a short uuid-prefixed date so filenames
sort chronologically. Files are append-only; nothing rewrites an old
session, so an interrupted chat is recoverable.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any


def _dir(root: Path) -> Path:
    d = root / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(root: Path, sid: str) -> Path:
    return _dir(root) / f"{sid}.jsonl"


def _meta_path(root: Path, sid: str) -> Path:
    return _dir(root) / f"{sid}.meta.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON via tempfile + os.replace so a crash never leaves a half-file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _derive_title(turns: list[dict]) -> str:
    """Mirrors the original list_sessions title behavior — first user message,
    truncated to 60 chars. Used as the fallback when no meta sidecar exists."""
    for t in turns:
        if t.get("role") == "user":
            return (t.get("content") or "")[:60]
    return "(empty)"


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


def read_meta(root: Path, sid: str) -> dict[str, Any]:
    """Return persisted metadata for a session, falling back to derived defaults
    when the sidecar is missing. Sessions without a sidecar (e.g. ones created
    before this feature shipped) appear in the listing with sensible defaults
    so nothing requires a migration step."""
    path = _meta_path(root, sid)
    persisted: dict[str, Any] = {}
    if path.exists():
        try:
            persisted = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            persisted = {}
    if not isinstance(persisted, dict):
        persisted = {}

    jsonl = _session_path(root, sid)
    persisted_title = persisted.get("title")
    turns = load_session(root, sid) if not persisted_title else []
    if jsonl.exists():
        mtime_iso = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc).isoformat()
        ctime_iso = datetime.fromtimestamp(jsonl.stat().st_ctime, tz=timezone.utc).isoformat()
    else:
        mtime_iso = ctime_iso = _now_iso()

    return {
        "id": sid,
        "title": persisted_title or _derive_title(turns),
        "title_locked": bool(persisted.get("title_locked", False)),
        "pinned": bool(persisted.get("pinned", False)),
        "folder_id": persisted.get("folder_id"),
        "created_at": persisted.get("created_at") or ctime_iso,
        "updated_at": persisted.get("updated_at") or mtime_iso,
    }


def write_meta(root: Path, sid: str, **fields: Any) -> dict[str, Any]:
    """Update metadata fields and persist. Setting `title` implicitly sets
    `title_locked=True` unless caller passes title_locked explicitly. Fields
    not supplied are preserved from the prior meta."""
    current = read_meta(root, sid)

    # Title implicitly locks unless caller is explicit (e.g. the auto-titler).
    if "title" in fields and "title_locked" not in fields:
        fields["title_locked"] = True

    allowed = {"title", "title_locked", "pinned", "folder_id", "created_at"}
    for key, value in fields.items():
        if key in allowed:
            current[key] = value

    current["id"] = sid
    current["updated_at"] = _now_iso()
    _atomic_write_json(_meta_path(root, sid), current)
    return current


def delete_session(root: Path, sid: str) -> None:
    """Remove both the .jsonl and .meta.json files. Idempotent — missing files
    are silently ignored so the API delete handler can be a single call."""
    for p in (_session_path(root, sid), _meta_path(root, sid)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def list_sessions(root: Path, *, limit: int = 200) -> list[dict]:
    """Return session summaries, newest first.

    Summary: {id, title, message_count, last_ts, pinned, folder_id,
    title_locked, created_at, updated_at}. Empty sessions (no turns
    written yet) are skipped. Default limit raised to 200 because the
    sidebar is the only consumer and it wants the full history.
    """
    files = sorted(_dir(root).glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict] = []
    for f in files[:limit]:
        sid = f.stem
        turns = load_session(root, sid)
        if not turns:
            continue
        meta = read_meta(root, sid)
        out.append({
            "id": sid,
            "title": meta["title"],
            "title_locked": meta["title_locked"],
            "message_count": len(turns),
            "last_ts": turns[-1]["ts"],
            "pinned": meta["pinned"],
            "folder_id": meta["folder_id"],
            "created_at": meta["created_at"],
            "updated_at": meta["updated_at"],
        })
    return out
