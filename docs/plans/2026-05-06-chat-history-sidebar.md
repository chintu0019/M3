# Chat History Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsable left sidebar that lists every past chat session, supports user-named folders + pinning + auto-naming, and persists indefinitely until manual deletion.

**Architecture:** Extend the existing per-session `.jsonl` storage with sibling `.meta.json` sidecars and a top-level `folders.json`. Lift the active session id from `ChatRail` into `Canvas`, then add a new `ChatHistorySidebar` component to the left of `ChatRail`. Auto-naming runs as a best-effort post-hook after the first assistant turn.

**Tech Stack:** Python (FastAPI, pytest), TypeScript (React, Vite). No new dependencies.

**Spec:** [docs/specs/2026-05-06-chat-history-sidebar-design.md](../specs/2026-05-06-chat-history-sidebar-design.md)

---

## File Structure

### Backend

| File | Responsibility |
|---|---|
| `server/m3/brain/chats.py` (modify) | Add `read_meta`, `write_meta`, `delete_session`. Extend `list_sessions` with new fields. |
| `server/m3/brain/folders.py` (create) | CRUD over `folders.json`. |
| `server/m3/api/chats.py` (modify) | Add PATCH/DELETE chat routes + folder CRUD routes. |
| `server/m3/api/chat.py` (modify) | After first assistant turn, fire-and-forget the auto-title pass. |
| `server/m3/brain/auto_title.py` (create) | The auto-title routine. Pure function; takes the LLM and the first turn pair. |
| `server/tests/brain/test_chats.py` (modify) | Tests for meta read/write/delete + extended list. |
| `server/tests/brain/test_folders.py` (create) | Folder CRUD tests. |
| `server/tests/brain/test_auto_title.py` (create) | Auto-title pass tests with stubbed LLM. |
| `server/tests/api/test_chats_api.py` (modify) | Tests for new PATCH/DELETE + folder routes. |

### Frontend

| File | Responsibility |
|---|---|
| `client/src/api/client.ts` (modify) | Extend types; add `patchChat`, `deleteChat`, folder CRUD methods. |
| `client/src/lib/recency.ts` (create) | Bucket a timestamp into Today/Yesterday/7d/30d/Older. |
| `client/src/components/canvas/ChatHistorySidebar.tsx` (create) | The sidebar shell: header, sections, expand/collapse. |
| `client/src/components/canvas/sidebar/ChatRow.tsx` (create) | One chat row: title, hover reveal, inline rename, context menu. |
| `client/src/components/canvas/sidebar/FolderRow.tsx` (create) | One folder row: expand toggle, drop target, rename, delete. |
| `client/src/components/canvas/sidebar/RowMenu.tsx` (create) | Shared overflow popover used by chat/folder rows. |
| `client/src/components/canvas/ChatRail.tsx` (modify) | Accept `sessionId` as a prop instead of owning it; remove localStorage logic from here. |
| `client/src/views/Canvas.tsx` (modify) | Own `activeSessionId` state, render the sidebar, pass id down. |
| `client/src/index.css` (modify) | Sidebar styles, matching existing `m3-chat-rail__*` aesthetic. |

---

## Task 1: Backend — meta sidecar read/write primitives

**Files:**
- Modify: `server/m3/brain/chats.py`
- Test: `server/tests/brain/test_chats.py`

- [ ] **Step 1: Write failing tests for `read_meta` defaults and `write_meta` round-trip**

Append to `server/tests/brain/test_chats.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd server && pytest tests/brain/test_chats.py -v`
Expected: FAIL — `module 'm3.brain.chats' has no attribute 'read_meta'`.

- [ ] **Step 3: Implement primitives in `server/m3/brain/chats.py`**

Add these imports at top (replace the existing import block):

```python
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any
```

Add these helpers above `new_session`:

```python
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
```

Add `read_meta`, `write_meta`, `delete_session` below `load_session`:

```python
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

    jsonl = _session_path(root, sid)
    turns = load_session(root, sid)
    if jsonl.exists():
        mtime_iso = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc).isoformat()
        ctime_iso = datetime.fromtimestamp(jsonl.stat().st_ctime, tz=timezone.utc).isoformat()
    else:
        mtime_iso = ctime_iso = _now_iso()

    return {
        "id": sid,
        "title": persisted.get("title") or _derive_title(turns),
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
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `cd server && pytest tests/brain/test_chats.py -v`
Expected: PASS for all new tests; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add server/m3/brain/chats.py server/tests/brain/test_chats.py
git commit -m "feat(chats): meta sidecar primitives — read/write/delete"
```

---

## Task 2: Backend — extend `list_sessions` with new fields

**Files:**
- Modify: `server/m3/brain/chats.py`
- Test: `server/tests/brain/test_chats.py`

- [ ] **Step 1: Write failing tests**

Append to `server/tests/brain/test_chats.py`:

```python
def test_list_sessions_includes_meta_fields(tmp_brain: Path):
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "hello")
    _chats.write_meta(tmp_brain, sid, title="Custom", pinned=True, folder_id="f_x")
    sessions = _chats.list_sessions(tmp_brain)
    assert sessions[0]["title"] == "Custom"
    assert sessions[0]["pinned"] is True
    assert sessions[0]["folder_id"] == "f_x"
    assert sessions[0]["updated_at"]


def test_list_sessions_without_sidecar_uses_defaults(tmp_brain: Path):
    """Sessions from before the sidecar feature shipped still appear."""
    sid = _chats.new_session(tmp_brain)
    _chats.append_turn(tmp_brain, sid, "user", "legacy chat")
    sessions = _chats.list_sessions(tmp_brain)
    assert sessions[0]["title"] == "legacy chat"
    assert sessions[0]["pinned"] is False
    assert sessions[0]["folder_id"] is None
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd server && pytest tests/brain/test_chats.py::test_list_sessions_includes_meta_fields -v`
Expected: FAIL — `KeyError: 'pinned'` or similar.

- [ ] **Step 3: Update `list_sessions` to merge meta**

Replace the existing `list_sessions` body in `server/m3/brain/chats.py`:

```python
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
```

- [ ] **Step 4: Run all chat tests, confirm pass**

Run: `cd server && pytest tests/brain/test_chats.py -v`
Expected: PASS for all (existing tests use `title` / `id` / `last_ts` which are unchanged).

- [ ] **Step 5: Commit**

```bash
git add server/m3/brain/chats.py server/tests/brain/test_chats.py
git commit -m "feat(chats): list_sessions includes pinned/folder/timestamps"
```

---

## Task 3: Backend — folders module

**Files:**
- Create: `server/m3/brain/folders.py`
- Test: `server/tests/brain/test_folders.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/brain/test_folders.py`:

```python
from __future__ import annotations

from pathlib import Path

from m3.brain import folders as _folders


def test_list_folders_empty(tmp_brain: Path):
    assert _folders.list_folders(tmp_brain) == []


def test_create_folder_returns_record(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="Work")
    assert f["name"] == "Work"
    assert f["id"].startswith("f_")
    assert f["sort_order"] == 0


def test_list_folders_after_create(tmp_brain: Path):
    f1 = _folders.create_folder(tmp_brain, name="Work")
    f2 = _folders.create_folder(tmp_brain, name="Side")
    listed = _folders.list_folders(tmp_brain)
    assert [f["id"] for f in listed] == [f1["id"], f2["id"]]
    assert listed[1]["sort_order"] == 1


def test_update_folder_rename(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="Old")
    _folders.update_folder(tmp_brain, f["id"], name="New")
    assert _folders.list_folders(tmp_brain)[0]["name"] == "New"


def test_update_folder_reorder(tmp_brain: Path):
    f1 = _folders.create_folder(tmp_brain, name="A")
    f2 = _folders.create_folder(tmp_brain, name="B")
    _folders.update_folder(tmp_brain, f2["id"], sort_order=0)
    _folders.update_folder(tmp_brain, f1["id"], sort_order=1)
    ids = [f["id"] for f in _folders.list_folders(tmp_brain)]
    assert ids == [f2["id"], f1["id"]]


def test_update_unknown_folder_raises(tmp_brain: Path):
    import pytest
    with pytest.raises(KeyError):
        _folders.update_folder(tmp_brain, "f_nope", name="X")


def test_delete_folder(tmp_brain: Path):
    f = _folders.create_folder(tmp_brain, name="X")
    _folders.delete_folder(tmp_brain, f["id"])
    assert _folders.list_folders(tmp_brain) == []


def test_delete_folder_idempotent(tmp_brain: Path):
    _folders.delete_folder(tmp_brain, "f_nope")  # must not raise
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd server && pytest tests/brain/test_folders.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `server/m3/brain/folders.py`**

```python
"""Folders for organizing chat sessions.

Single file at ~/brain/chats/folders.json. CRUD over a small list of
folder records: { id, name, sort_order }. Sort order is dense and
maintained explicitly by callers (the API layer renumbers when needed).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any


def _path(root: Path) -> Path:
    return root / "chats" / "folders.json"


def _load(root: Path) -> list[dict]:
    p = _path(root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    items = data.get("folders") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _atomic_save(root: Path, folders: list[dict]) -> None:
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"folders": folders}, fh)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def list_folders(root: Path) -> list[dict]:
    folders = _load(root)
    return sorted(folders, key=lambda f: f.get("sort_order", 0))


def create_folder(root: Path, *, name: str) -> dict:
    folders = _load(root)
    record = {
        "id": f"f_{uuid.uuid4().hex[:8]}",
        "name": name,
        "sort_order": len(folders),
    }
    folders.append(record)
    _atomic_save(root, folders)
    return record


def update_folder(root: Path, fid: str, **fields: Any) -> dict:
    folders = _load(root)
    for f in folders:
        if f["id"] == fid:
            if "name" in fields:
                f["name"] = fields["name"]
            if "sort_order" in fields:
                f["sort_order"] = int(fields["sort_order"])
            _atomic_save(root, folders)
            return f
    raise KeyError(fid)


def delete_folder(root: Path, fid: str) -> None:
    folders = _load(root)
    remaining = [f for f in folders if f["id"] != fid]
    if len(remaining) == len(folders):
        return  # idempotent
    _atomic_save(root, remaining)
```

- [ ] **Step 4: Run tests**

Run: `cd server && pytest tests/brain/test_folders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/m3/brain/folders.py server/tests/brain/test_folders.py
git commit -m "feat(folders): folders.json CRUD module"
```

---

## Task 4: Backend — PATCH/DELETE chat routes

**Files:**
- Modify: `server/m3/api/chats.py`
- Test: `server/tests/api/test_chats_api.py`

- [ ] **Step 1: Write failing tests**

Append to `server/tests/api/test_chats_api.py`:

```python
def test_patch_chat_sets_title_and_locks(app):
    c = TestClient(app)
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "hi")
    r = c.patch(f"/api/v1/chats/{sid}", json={"title": "Custom"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Custom"
    assert body["title_locked"] is True


def test_patch_chat_pin(app):
    c = TestClient(app)
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "hi")
    r = c.patch(f"/api/v1/chats/{sid}", json={"pinned": True})
    assert r.status_code == 200
    assert r.json()["pinned"] is True


def test_patch_chat_move_to_folder(app):
    c = TestClient(app)
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "hi")
    fid = c.post("/api/v1/folders", json={"name": "Work"}).json()["id"]
    r = c.patch(f"/api/v1/chats/{sid}", json={"folder_id": fid})
    assert r.status_code == 200
    assert r.json()["folder_id"] == fid


def test_patch_unknown_chat_returns_404(app):
    c = TestClient(app)
    r = c.patch("/api/v1/chats/nope", json={"title": "x"})
    assert r.status_code == 404


def test_delete_chat_removes_files(app):
    c = TestClient(app)
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "hi")
    r = c.delete(f"/api/v1/chats/{sid}")
    assert r.status_code == 204
    assert c.get("/api/v1/chats").json() == []


def test_delete_chat_idempotent(app):
    c = TestClient(app)
    r = c.delete("/api/v1/chats/never-existed")
    assert r.status_code == 204
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd server && pytest tests/api/test_chats_api.py -v`
Expected: FAIL on the new tests (404 not yet handled correctly, route missing).

- [ ] **Step 3: Update `server/m3/api/chats.py`**

Replace the file with:

```python
"""HTTP surface for persisted chat sessions and folders."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from m3.brain import chats as _chats
from m3.brain import folders as _folders


class SessionSummary(BaseModel):
    id: str
    title: str
    title_locked: bool = False
    message_count: int
    last_ts: str
    pinned: bool = False
    folder_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SessionTurn(BaseModel):
    ts: str
    role: str
    content: str
    events: list = []


class NewSessionResponse(BaseModel):
    id: str


class SessionResponse(BaseModel):
    id: str
    turns: list[SessionTurn]


class PatchSessionRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    folder_id: Optional[str] = None  # explicit None means "remove from folder"

    # Pydantic v2: distinguish "field not sent" from "sent as null".
    model_config = {"extra": "ignore"}


class FolderRecord(BaseModel):
    id: str
    name: str
    sort_order: int


class CreateFolderRequest(BaseModel):
    name: str


class PatchFolderRequest(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


def build_chats_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["chats"])

    @router.get("/chats", response_model=list[SessionSummary])
    async def list_chats():
        return _chats.list_sessions(brain_root)

    @router.post("/chats", response_model=NewSessionResponse)
    async def new_chat():
        return NewSessionResponse(id=_chats.new_session(brain_root))

    @router.get("/chats/{sid}", response_model=SessionResponse)
    async def get_chat(sid: str):
        turns = _chats.load_session(brain_root, sid)
        if not turns:
            raise HTTPException(status_code=404, detail="session not found or empty")
        return SessionResponse(id=sid, turns=[SessionTurn(**t) for t in turns])

    @router.patch("/chats/{sid}", response_model=SessionSummary)
    async def patch_chat(sid: str, body: PatchSessionRequest):
        # Disallow patching a session that has no turns yet — the listing
        # would never show it anyway, and it makes the 404 unambiguous.
        if not _chats.load_session(brain_root, sid):
            raise HTTPException(status_code=404, detail="session not found or empty")
        update = body.model_dump(exclude_unset=True)
        meta = _chats.write_meta(brain_root, sid, **update)
        # Re-derive message_count + last_ts from the listing-style read for
        # response consistency.
        turns = _chats.load_session(brain_root, sid)
        return SessionSummary(
            id=sid,
            title=meta["title"],
            title_locked=meta["title_locked"],
            message_count=len(turns),
            last_ts=turns[-1]["ts"],
            pinned=meta["pinned"],
            folder_id=meta["folder_id"],
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
        )

    @router.delete("/chats/{sid}", status_code=204)
    async def delete_chat(sid: str):
        _chats.delete_session(brain_root, sid)
        return Response(status_code=204)

    @router.get("/folders", response_model=list[FolderRecord])
    async def list_folders():
        return _folders.list_folders(brain_root)

    @router.post("/folders", response_model=FolderRecord)
    async def create_folder(body: CreateFolderRequest):
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name is required")
        return _folders.create_folder(brain_root, name=body.name.strip())

    @router.patch("/folders/{fid}", response_model=FolderRecord)
    async def patch_folder(fid: str, body: PatchFolderRequest):
        update = body.model_dump(exclude_unset=True)
        try:
            return _folders.update_folder(brain_root, fid, **update)
        except KeyError:
            raise HTTPException(status_code=404, detail="folder not found")

    @router.delete("/folders/{fid}", status_code=204)
    async def delete_folder(fid: str):
        _folders.delete_folder(brain_root, fid)
        # Orphan any chats that pointed at this folder back to no-folder so
        # the UI doesn't render dangling references.
        for s in _chats.list_sessions(brain_root):
            if s["folder_id"] == fid:
                _chats.write_meta(brain_root, s["id"], folder_id=None)
        return Response(status_code=204)

    return router
```

- [ ] **Step 4: Run tests**

Run: `cd server && pytest tests/api/test_chats_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/m3/api/chats.py server/tests/api/test_chats_api.py
git commit -m "feat(api): PATCH/DELETE chat + folder CRUD"
```

---

## Task 5: Backend — folder-orphan-on-delete test

**Files:**
- Test: `server/tests/api/test_chats_api.py`

This is the one cross-cutting behavior the spec calls out (delete folder → chats orphan to `null`). Worth its own test even though Task 4 handles it.

- [ ] **Step 1: Write the test**

Append to `server/tests/api/test_chats_api.py`:

```python
def test_delete_folder_orphans_member_chats(app):
    c = TestClient(app)
    fid = c.post("/api/v1/folders", json={"name": "Work"}).json()["id"]
    sid = c.post("/api/v1/chats").json()["id"]
    _chats.append_turn(app.state._brain, sid, "user", "hi")
    c.patch(f"/api/v1/chats/{sid}", json={"folder_id": fid})
    c.delete(f"/api/v1/folders/{fid}")
    listing = c.get("/api/v1/chats").json()
    assert listing[0]["folder_id"] is None
```

- [ ] **Step 2: Run, expect PASS** (Task 4 already handles this)

Run: `cd server && pytest tests/api/test_chats_api.py::test_delete_folder_orphans_member_chats -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add server/tests/api/test_chats_api.py
git commit -m "test(api): folder delete orphans member chats"
```

---

## Task 6: Backend — auto-title routine

**Files:**
- Create: `server/m3/brain/auto_title.py`
- Create: `server/tests/brain/test_auto_title.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/brain/test_auto_title.py`:

```python
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
```

Note: `pytest-asyncio>=0.24` is already a dev dep in `server/pyproject.toml`. The project does NOT set `asyncio_mode = "auto"`, so the explicit `@pytest.mark.asyncio` decorators above are required.

- [ ] **Step 2: (no-op) verify pytest-asyncio is on PYTHONPATH**

Run: `cd server && python -c "import pytest_asyncio; print(pytest_asyncio.__version__)"`
Expected: prints a version. If not, run `uv sync` from `server/`.

- [ ] **Step 3: Run tests, confirm failure**

Run: `cd server && pytest tests/brain/test_auto_title.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement `server/m3/brain/auto_title.py`**

```python
"""Best-effort auto-naming for chat sessions.

After the first assistant turn lands on a fresh session, ask the configured
LLM for a 3-6 word title and persist it. Locked titles (user renames) are
skipped. Failures are swallowed — the user always sees *some* title via the
derived-first-user-message fallback in read_meta.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from m3.brain import chats as _chats

logger = logging.getLogger(__name__)

_PROMPT = (
    "You are titling a chat conversation for a sidebar list. "
    "Read the user's first message and the assistant's first reply, then "
    "produce a concise 3–6 word title that captures the topic. "
    "Output ONLY the title text — no quotes, no punctuation at the end, "
    "no leading 'Title:'."
)


class _MinimalLLM(Protocol):
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...


def _clean(raw: str) -> str:
    s = (raw or "").strip()
    # Strip wrapping quotes and any trailing punctuation that adds no value.
    if len(s) >= 2 and s[0] in {'"', "'"} and s[-1] == s[0]:
        s = s[1:-1].strip()
    while s and s[-1] in {".", "!", "?"}:
        s = s[:-1].rstrip()
    return s[:60]


async def generate_and_save_title(root: Path, sid: str, llm: _MinimalLLM) -> None:
    """Generate a title for the given session and persist it via write_meta.

    Pre-conditions:
      - Session has at least one user turn AND one assistant turn.
      - Existing meta has title_locked == False.

    Always returns. Never raises. On any failure or pre-condition miss the
    function is a no-op and the derived title remains.
    """
    try:
        meta = _chats.read_meta(root, sid)
        if meta.get("title_locked"):
            return

        turns = _chats.load_session(root, sid)
        first_user = next((t for t in turns if t["role"] == "user"), None)
        first_asst = next((t for t in turns if t["role"] == "assistant"), None)
        if not first_user or not first_asst:
            return

        prompt = (
            f"User: {first_user['content'][:1000]}\n\n"
            f"Assistant: {first_asst['content'][:1500]}"
        )
        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_PROMPT,
            max_tokens=60,
            temperature=0.3,
        )
        title = _clean(raw)
        if not title:
            return

        # title_locked=False so future runs of this routine could still
        # update — though in practice we only fire this once per session.
        _chats.write_meta(root, sid, title=title, title_locked=False)
    except Exception as e:
        logger.warning("auto_title failed for session %s: %s", sid, e)
```

- [ ] **Step 5: Run tests**

Run: `cd server && pytest tests/brain/test_auto_title.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/m3/brain/auto_title.py server/tests/brain/test_auto_title.py
git commit -m "feat(chats): auto_title routine"
```

---

## Task 7: Backend — wire auto-title into chat route

**Files:**
- Modify: `server/m3/api/chat.py`
- Test: `server/tests/api/test_chat_api.py`

The auto-title should fire after the first assistant turn of a session. We schedule it as a background task so it never blocks the SSE stream's `[DONE]`.

- [ ] **Step 1: Look at the existing chat-api test to understand the harness**

Run: `cat server/tests/api/test_chat_api.py | head -60`

(Uses `TestClient` and a fake LLM factory passed to `build_app`.)

- [ ] **Step 2: Write a failing test for the auto-title hook**

Append to `server/tests/api/test_chat_api.py` (or create a new file `test_chat_auto_title.py` if the existing file uses fixtures incompatible with our needs — verify by reading first). The intent:

```python
def test_first_turn_triggers_auto_title(app_with_llm, fake_llm):
    """After the first user/assistant exchange, the session's title is
    generated by the LLM rather than left as the truncated first message."""
    c = TestClient(app_with_llm)
    sid = c.post("/api/v1/chats").json()["id"]
    fake_llm.set_completion_response("Refactor force layout")
    # Kick a chat turn
    with c.stream("POST", "/api/v1/chat",
                  json={"message": "Help me refactor force layout", "session_id": sid}) as r:
        for _ in r.iter_lines():
            pass
    # Allow the scheduled background task to run.
    import asyncio, time
    time.sleep(0.5)
    listing = c.get("/api/v1/chats").json()
    assert listing[0]["title"] == "Refactor force layout"
```

The current `FakeLLM` in `server/tests/conftest.py` only implements `complete_tool`. Extend it to also support `complete`. In `conftest.py`, modify `FakeLLM.__init__` to add a default and add the two methods at the bottom of the class:

```python
class FakeLLM:
    def __init__(self, canned: dict[str, dict[str, Any]] | None = None) -> None:
        self._canned = canned or {}
        self.calls: list[dict[str, Any]] = []
        self._completion = "Default title"

    def set_completion_response(self, text: str) -> None:
        self._completion = text

    async def complete(self, messages, system=None, max_tokens=4096, temperature=0.7):
        return self._completion

    # ... existing complete_tool unchanged ...
```

Also you'll need an `app_with_llm` fixture or whatever pattern `test_chat_api.py` uses — read it first to find the correct fixture name and reuse it as-is.

- [ ] **Step 3: Run test, expect failure**

Run: `cd server && pytest tests/api/test_chat_api.py::test_first_turn_triggers_auto_title -v`
Expected: FAIL — title is still the truncated user message.

- [ ] **Step 4: Modify `server/m3/api/chat.py` to schedule auto_title**

After the existing persist block (around line 83-93), add:

```python
            if body.session_id:
                try:
                    _chats.append_turn(brain_root, body.session_id, "user", body.message)
                    assistant_content = final_text or (f"(error) {error_text}" if error_text else "")
                    _chats.append_turn(
                        brain_root, body.session_id, "assistant",
                        assistant_content, events=collected_events,
                    )
                    # Auto-title on the first exchange of a session.
                    # We re-load the session here rather than tracking turn
                    # count separately — list_session is cheap on a 2-turn file.
                    turns = _chats.load_session(brain_root, body.session_id)
                    user_turns = sum(1 for t in turns if t["role"] == "user")
                    if user_turns == 1:
                        # Fire-and-forget; never block [DONE].
                        import asyncio
                        from m3.brain.auto_title import generate_and_save_title
                        asyncio.create_task(
                            generate_and_save_title(brain_root, body.session_id, llm)
                        )
                except OSError:
                    pass
            yield "data: [DONE]\n\n"
```

Note the existing `llm` is in scope from line 43 (`llm = _get_llm()`). The `import` is placed inline to keep the change small and avoid touching unrelated imports.

- [ ] **Step 5: Run all chat-api tests**

Run: `cd server && pytest tests/api/test_chat_api.py -v`
Expected: PASS — including pre-existing tests.

- [ ] **Step 6: Run full backend test suite**

Run: `cd server && pytest -x`
Expected: PASS overall.

- [ ] **Step 7: Commit**

```bash
git add server/m3/api/chat.py server/tests/api/test_chat_api.py server/tests/conftest.py
git commit -m "feat(chat): fire auto-title after first assistant turn"
```

---

## Task 8: Frontend — extend API client

**Files:**
- Modify: `client/src/api/client.ts`

- [ ] **Step 1: Update types**

In `client/src/api/client.ts`, replace the `ChatSessionSummary` interface:

```typescript
export interface ChatSessionSummary {
  id: string;
  title: string;
  title_locked: boolean;
  message_count: number;
  last_ts: string;
  pinned: boolean;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatFolder {
  id: string;
  name: string;
  sort_order: number;
}
```

- [ ] **Step 2: Add API methods**

Insert into the `api` object (after `getChat`):

```typescript
  patchChat: (
    sid: string,
    fields: { title?: string; pinned?: boolean; folder_id?: string | null },
  ) =>
    request<ChatSessionSummary>(`/api/v1/chats/${encodeURIComponent(sid)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),

  deleteChat: (sid: string) =>
    request<void>(`/api/v1/chats/${encodeURIComponent(sid)}`, { method: "DELETE" }),

  listFolders: () => request<ChatFolder[]>("/api/v1/folders"),

  createFolder: (name: string) =>
    request<ChatFolder>("/api/v1/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  patchFolder: (fid: string, fields: { name?: string; sort_order?: number }) =>
    request<ChatFolder>(`/api/v1/folders/${encodeURIComponent(fid)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }),

  deleteFolder: (fid: string) =>
    request<void>(`/api/v1/folders/${encodeURIComponent(fid)}`, { method: "DELETE" }),
```

Note: the `request` helper at line 15 may not handle 204 No Content. If TypeScript complains or the call fails at runtime, update `request` to short-circuit on 204:

```typescript
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}
```

- [ ] **Step 3: Verify the client builds**

Run: `cd client && npm run build` (or `npx tsc --noEmit`)
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add client/src/api/client.ts
git commit -m "feat(api-client): chat patch/delete + folder CRUD"
```

---

## Task 9: Frontend — recency bucketing helper

**Files:**
- Create: `client/src/lib/recency.ts`

- [ ] **Step 1: Create the helper**

```typescript
// Bucket a chat by its updated_at relative to "now" (default Date.now()).
// Mirrors the visual sections in the sidebar — the only consumer.

export type RecencyBucket =
  | "today"
  | "yesterday"
  | "previous7"
  | "previous30"
  | "older";

export const BUCKET_LABEL: Record<RecencyBucket, string> = {
  today: "Today",
  yesterday: "Yesterday",
  previous7: "Previous 7 Days",
  previous30: "Previous 30 Days",
  older: "Older",
};

export const BUCKET_ORDER: RecencyBucket[] = [
  "today",
  "yesterday",
  "previous7",
  "previous30",
  "older",
];

export function bucketFor(iso: string, now: Date = new Date()): RecencyBucket {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "older";
  const day = 86_400_000;
  const startOfToday = new Date(
    now.getFullYear(), now.getMonth(), now.getDate(),
  ).getTime();
  const diff = startOfToday - ts;
  if (ts >= startOfToday) return "today";
  if (ts >= startOfToday - day) return "yesterday";
  if (diff < 7 * day) return "previous7";
  if (diff < 30 * day) return "previous30";
  return "older";
}
```

- [ ] **Step 2: Sanity check via build**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add client/src/lib/recency.ts
git commit -m "feat(client): recency bucketing helper"
```

---

## Task 10: Frontend — lift sessionId to Canvas

**Files:**
- Modify: `client/src/views/Canvas.tsx`
- Modify: `client/src/components/canvas/ChatRail.tsx`

ChatRail today owns `sessionId` via internal state + localStorage. We lift it up so the sidebar (selecting a row) and the rail (rendering a session's turns) share a single source of truth.

- [ ] **Step 1: Refactor ChatRail to controlled session id**

Edit `client/src/components/canvas/ChatRail.tsx`. Change the props interface to add `sessionId` and `onSessionChange`:

```typescript
export interface ChatRailProps {
  onTyping: (text: string) => void;
  onSend: (text: string) => void;
  onCitation: (citedRef: CitedRef) => void;
  resolveCitation: (itemId: string) => CitedRef | null;
  cited: CitedRef[];
  onCitedClick: (id: string) => void;
  onReset: () => void;
  suggestions: string[];
  /** Currently active session id. Null = no session yet (mint on first send). */
  sessionId: string | null;
  /** Notify parent of session id changes (mint on first send, reset on "+"). */
  onSessionChange: (sid: string | null) => void;
}
```

Remove the internal `useState<string | null>` for `sessionId`. Replace with destructured props:

```typescript
export function ChatRail({
  onTyping, onSend, onCitation, resolveCitation, cited, onCitedClick, onReset,
  suggestions, sessionId, onSessionChange,
}: ChatRailProps) {
  const [turns, setTurns] = useState<RailTurn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  // ... rest unchanged ...
```

Replace the hydration `useEffect` to react to sessionId prop changes (so clicking a different session in the sidebar rehydrates):

```typescript
  useEffect(() => {
    if (!sessionId) {
      setTurns([]);
      return;
    }
    let cancelled = false;
    api.getChat(sessionId)
      .then(res => {
        if (cancelled) return;
        const restored: RailTurn[] = res.turns.map(t => ({
          role: t.role === "user" ? "user" : "assistant",
          text: t.content,
          cites: [],
        }));
        setTurns(restored);
      })
      .catch(() => {
        // Session disappeared on the server — tell parent so it can drop.
        onSessionChange(null);
      });
    return () => { cancelled = true; };
  }, [sessionId, onSessionChange]);
```

Replace `ensureSessionId` to push minted ids upward:

```typescript
  async function ensureSessionId(): Promise<string> {
    if (sessionId) return sessionId;
    const { id } = await api.newChat();
    onSessionChange(id);
    return id;
  }
```

Replace `reset` to delegate session minting to the parent:

```typescript
  async function reset() {
    cancelRef.current.cancelled = true;
    setTurns([]);
    setStreaming(false);
    setCurrentStep(null);
    onSessionChange(null); // parent will mint a fresh session lazily on next send
    onReset();
  }
```

- [ ] **Step 2: Move sessionId ownership into Canvas**

Edit `client/src/views/Canvas.tsx`. Near the other `useState` calls inside `Canvas()`, add:

```typescript
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : localStorage.getItem("m3-session-id"),
  );

  // Persist whenever it changes — single source of truth.
  useEffect(() => {
    if (activeSessionId) localStorage.setItem("m3-session-id", activeSessionId);
    else localStorage.removeItem("m3-session-id");
  }, [activeSessionId]);
```

Find the `<ChatRail .../>` JSX and add the new props:

```tsx
      <ChatRail
        // ... existing props ...
        sessionId={activeSessionId}
        onSessionChange={setActiveSessionId}
      />
```

- [ ] **Step 3: Type-check**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Smoke test in dev server**

Run: `cd client && npm run dev` — open the app, send a message, reload page. The chat should still hydrate.

If running this plan via an agent harness with `preview_*` tools available, prefer those.

- [ ] **Step 5: Commit**

```bash
git add client/src/views/Canvas.tsx client/src/components/canvas/ChatRail.tsx
git commit -m "refactor(chat): lift sessionId from ChatRail to Canvas"
```

---

## Task 11: Frontend — shared RowMenu popover

**Files:**
- Create: `client/src/components/canvas/sidebar/RowMenu.tsx`

A small overflow popover used by both `ChatRow` and `FolderRow`. Build it first so the row tasks can use it.

- [ ] **Step 1: Create the file**

```typescript
// Generic overflow menu used by chat rows and folder rows in the sidebar.
// Keep it DUMB — caller provides items + handlers. Closes on outside click,
// Escape, or item activation.

import { useEffect, useRef } from "react";

export interface RowMenuItem {
  label: string;
  /** Optional submenu items — when present, hovering shows a child menu. */
  children?: RowMenuItem[];
  onClick?: () => void;
  destructive?: boolean;
  divider?: boolean;
}

export interface RowMenuProps {
  items: RowMenuItem[];
  onClose: () => void;
  /** Anchor coordinates (page x, y) — caller computes from a DOM rect or click event. */
  x: number;
  y: number;
}

export function RowMenu({ items, onClose, x, y }: RowMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="m3-row-menu"
      style={{ position: "fixed", left: x, top: y }}
      role="menu"
    >
      {items.map((it, i) =>
        it.divider ? (
          <div key={i} className="m3-row-menu__divider" />
        ) : it.children ? (
          <div key={i} className="m3-row-menu__item m3-row-menu__item--has-children" role="menuitem">
            <span>{it.label}</span>
            <span className="m3-row-menu__chevron">▸</span>
            <div className="m3-row-menu__submenu">
              {it.children.map((c, j) => (
                <button
                  key={j}
                  className={`m3-row-menu__item${c.destructive ? " m3-row-menu__item--danger" : ""}`}
                  role="menuitem"
                  onClick={() => { c.onClick?.(); onClose(); }}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <button
            key={i}
            className={`m3-row-menu__item${it.destructive ? " m3-row-menu__item--danger" : ""}`}
            role="menuitem"
            onClick={() => { it.onClick?.(); onClose(); }}
          >
            {it.label}
          </button>
        )
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/canvas/sidebar/RowMenu.tsx
git commit -m "feat(sidebar): generic RowMenu popover"
```

---

## Task 12: Frontend — ChatRow component

**Files:**
- Create: `client/src/components/canvas/sidebar/ChatRow.tsx`

- [ ] **Step 1: Create the component**

```typescript
// One row in the sidebar listing a chat session. Props are deliberately
// dumb — all mutating actions are passed in by the parent so the parent
// owns the optimistic-update + revert logic.

import { useEffect, useRef, useState } from "react";
import type { ChatFolder, ChatSessionSummary } from "../../../api/client";
import { RowMenu, type RowMenuItem } from "./RowMenu";

export interface ChatRowProps {
  chat: ChatSessionSummary;
  folders: ChatFolder[];
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onTogglePin: () => void;
  onMoveToFolder: (folderId: string | null) => void;
  onDelete: () => void;
  onDragStart?: (e: React.DragEvent) => void;
}

export function ChatRow({
  chat, folders, active, onSelect, onRename, onTogglePin, onMoveToFolder,
  onDelete, onDragStart,
}: ChatRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== chat.title) onRename(trimmed);
    setEditing(false);
  }

  const moveItems: RowMenuItem[] = [
    {
      label: "No folder",
      onClick: () => onMoveToFolder(null),
    },
    ...folders.map(f => ({ label: f.name, onClick: () => onMoveToFolder(f.id) })),
  ];

  const items: RowMenuItem[] = [
    { label: chat.pinned ? "Unpin" : "Pin", onClick: onTogglePin },
    { label: "Move to…", children: moveItems },
    { label: "Rename", onClick: () => setEditing(true) },
    { divider: true, label: "" },
    { label: "Delete", destructive: true, onClick: () => {
        if (window.confirm(`Delete "${chat.title}"? This cannot be undone.`)) onDelete();
      } },
  ];

  return (
    <div
      className={`m3-chat-row${active ? " m3-chat-row--active" : ""}`}
      onClick={() => !editing && onSelect()}
      onContextMenu={e => {
        e.preventDefault();
        setMenu({ x: e.clientX, y: e.clientY });
      }}
      onDoubleClick={e => { e.stopPropagation(); setEditing(true); }}
      draggable={!editing}
      onDragStart={onDragStart}
      role="button"
      tabIndex={0}
    >
      {editing ? (
        <input
          ref={inputRef}
          className="m3-chat-row__rename"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setDraft(chat.title); setEditing(false); }
          }}
          onClick={e => e.stopPropagation()}
        />
      ) : (
        <span className="m3-chat-row__title">{chat.title}</span>
      )}

      <div className="m3-chat-row__actions" onClick={e => e.stopPropagation()}>
        <button
          className={`m3-chat-row__pin${chat.pinned ? " m3-chat-row__pin--on" : ""}`}
          onClick={onTogglePin}
          title={chat.pinned ? "Unpin" : "Pin"}
          aria-label={chat.pinned ? "Unpin" : "Pin"}
        >
          ★
        </button>
        <button
          className="m3-chat-row__menu"
          onClick={e => setMenu({ x: e.clientX, y: e.clientY })}
          aria-label="More actions"
        >
          ⋯
        </button>
      </div>

      {menu && <RowMenu items={items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/canvas/sidebar/ChatRow.tsx
git commit -m "feat(sidebar): ChatRow component"
```

---

## Task 13: Frontend — FolderRow component

**Files:**
- Create: `client/src/components/canvas/sidebar/FolderRow.tsx`

- [ ] **Step 1: Create the component**

```typescript
// Folder row: header (expand toggle + name + count + actions). Children
// (the foldered chats) are rendered by the parent — this component only
// owns the header and exposes drop-target behavior for moving chats in.

import { useEffect, useRef, useState } from "react";
import type { ChatFolder } from "../../../api/client";
import { RowMenu, type RowMenuItem } from "./RowMenu";

export interface FolderRowProps {
  folder: ChatFolder;
  childCount: number;
  expanded: boolean;
  onToggle: () => void;
  onRename: (name: string) => void;
  onDelete: () => void;
  onDropChat: (chatId: string) => void;
}

export function FolderRow({
  folder, childCount, expanded, onToggle, onRename, onDelete, onDropChat,
}: FolderRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(folder.name);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== folder.name) onRename(trimmed);
    setEditing(false);
  }

  const items: RowMenuItem[] = [
    { label: "Rename", onClick: () => setEditing(true) },
    { divider: true, label: "" },
    {
      label: "Delete folder",
      destructive: true,
      onClick: () => {
        const msg = childCount > 0
          ? `Delete "${folder.name}"? ${childCount} chat${childCount === 1 ? "" : "s"} will move out of the folder (not deleted).`
          : `Delete "${folder.name}"?`;
        if (window.confirm(msg)) onDelete();
      },
    },
  ];

  return (
    <div
      className={`m3-folder-row${dragOver ? " m3-folder-row--drop" : ""}`}
      onContextMenu={e => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY }); }}
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault();
        setDragOver(false);
        const cid = e.dataTransfer.getData("application/x-chat-id");
        if (cid) onDropChat(cid);
      }}
    >
      <button className="m3-folder-row__toggle" onClick={onToggle} aria-label={expanded ? "Collapse" : "Expand"}>
        {expanded ? "▾" : "▸"}
      </button>

      {editing ? (
        <input
          ref={inputRef}
          className="m3-folder-row__rename"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setDraft(folder.name); setEditing(false); }
          }}
        />
      ) : (
        <span className="m3-folder-row__name" onDoubleClick={() => setEditing(true)}>
          {folder.name}
        </span>
      )}

      {childCount > 0 && <span className="m3-folder-row__count">{childCount}</span>}

      <button className="m3-folder-row__menu"
              onClick={e => setMenu({ x: e.clientX, y: e.clientY })}
              aria-label="More actions">⋯</button>

      {menu && <RowMenu items={items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/canvas/sidebar/FolderRow.tsx
git commit -m "feat(sidebar): FolderRow component"
```

---

## Task 14: Frontend — ChatHistorySidebar shell + read pass

**Files:**
- Create: `client/src/components/canvas/ChatHistorySidebar.tsx`

This task wires up data loading + section rendering. Mutating actions are wired in Task 15.

- [ ] **Step 1: Create the sidebar component**

```typescript
// Left-of-ChatRail sidebar: lists every persisted chat session, grouped
// into Pinned, Folders, and recency buckets. Owned by Canvas which passes
// the active session id and a callback to change it.
//
// Data is fetched from the server on mount and after any mutation (we
// keep the last `bumpKey` to force a refetch). Folder expand-state is
// local-only and persisted to localStorage per folder id.
//
// Drag-and-drop: a chat row sets `application/x-chat-id` on its
// dataTransfer. FolderRow handles drop-onto-folder. The "Chats" section
// header acts as a drop target meaning "remove from folder".

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ChatFolder, type ChatSessionSummary } from "../../api/client";
import { BUCKET_LABEL, BUCKET_ORDER, bucketFor, type RecencyBucket } from "../../lib/recency";
import { ChatRow } from "./sidebar/ChatRow";
import { FolderRow } from "./sidebar/FolderRow";

export interface ChatHistorySidebarProps {
  activeSessionId: string | null;
  onSelectSession: (sid: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Bumped by parent (Canvas) after sending a message so titles/timestamps refresh. */
  refreshKey: number;
}

export function ChatHistorySidebar({
  activeSessionId, onSelectSession, onNewChat, collapsed, onToggleCollapsed,
  refreshKey,
}: ChatHistorySidebarProps) {
  const [chats, setChats] = useState<ChatSessionSummary[]>([]);
  const [folders, setFolders] = useState<ChatFolder[]>([]);
  const [folderExpanded, setFolderExpanded] = useState<Record<string, boolean>>(() => {
    if (typeof window === "undefined") return {};
    try { return JSON.parse(localStorage.getItem("m3-folder-expanded") || "{}"); }
    catch { return {}; }
  });
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [folderDraft, setFolderDraft] = useState("");

  const refetch = useCallback(async () => {
    try {
      const [c, f] = await Promise.all([api.listChats(), api.listFolders()]);
      setChats(c);
      setFolders(f);
    } catch {
      // Empty/error: keep last successful snapshot.
    }
  }, []);

  useEffect(() => { refetch(); }, [refetch, refreshKey]);

  useEffect(() => {
    localStorage.setItem("m3-folder-expanded", JSON.stringify(folderExpanded));
  }, [folderExpanded]);

  // Patch helpers: optimistic update, revert on failure.
  const patchChat = useCallback(async (
    sid: string,
    fields: Parameters<typeof api.patchChat>[1],
  ) => {
    setChats(prev => prev.map(c => c.id === sid ? { ...c, ...fields } as ChatSessionSummary : c));
    try { await api.patchChat(sid, fields); }
    catch { refetch(); }
  }, [refetch]);

  const deleteChat = useCallback(async (sid: string) => {
    setChats(prev => prev.filter(c => c.id !== sid));
    try { await api.deleteChat(sid); }
    catch { refetch(); }
  }, [refetch]);

  const createFolder = useCallback(async (name: string) => {
    try {
      const f = await api.createFolder(name);
      setFolders(prev => [...prev, f]);
      setFolderExpanded(s => ({ ...s, [f.id]: true }));
    } catch { refetch(); }
  }, [refetch]);

  const renameFolder = useCallback(async (fid: string, name: string) => {
    setFolders(prev => prev.map(f => f.id === fid ? { ...f, name } : f));
    try { await api.patchFolder(fid, { name }); }
    catch { refetch(); }
  }, [refetch]);

  const deleteFolder = useCallback(async (fid: string) => {
    setFolders(prev => prev.filter(f => f.id !== fid));
    setChats(prev => prev.map(c => c.folder_id === fid ? { ...c, folder_id: null } : c));
    try { await api.deleteFolder(fid); }
    catch { refetch(); }
  }, [refetch]);

  // Sectioning.
  const pinned = useMemo(() => chats.filter(c => c.pinned), [chats]);
  const byFolder = useMemo(() => {
    const m = new Map<string, ChatSessionSummary[]>();
    for (const f of folders) m.set(f.id, []);
    for (const c of chats) {
      if (c.folder_id && m.has(c.folder_id)) m.get(c.folder_id)!.push(c);
    }
    return m;
  }, [chats, folders]);

  const unfoldered = useMemo(() => chats.filter(c => !c.folder_id), [chats]);
  const recency = useMemo(() => {
    const m: Record<RecencyBucket, ChatSessionSummary[]> = {
      today: [], yesterday: [], previous7: [], previous30: [], older: [],
    };
    for (const c of unfoldered) m[bucketFor(c.updated_at)].push(c);
    return m;
  }, [unfoldered]);

  // Drag-source for chat rows: pass the chat id. The 'application/x-chat-id'
  // payload is the contract between this component and FolderRow.
  function chatDragStart(sid: string) {
    return (e: React.DragEvent) => {
      e.dataTransfer.setData("application/x-chat-id", sid);
      e.dataTransfer.effectAllowed = "move";
    };
  }

  if (collapsed) {
    return (
      <aside className="m3-sidebar m3-sidebar--collapsed">
        <button className="m3-sidebar__expand" onClick={onToggleCollapsed} aria-label="Expand">›</button>
        <button className="m3-sidebar__newchat" onClick={onNewChat} title="New chat" aria-label="New chat">＋</button>
      </aside>
    );
  }

  function renderChat(c: ChatSessionSummary) {
    return (
      <ChatRow
        key={c.id}
        chat={c}
        folders={folders}
        active={c.id === activeSessionId}
        onSelect={() => onSelectSession(c.id)}
        onRename={title => patchChat(c.id, { title })}
        onTogglePin={() => patchChat(c.id, { pinned: !c.pinned })}
        onMoveToFolder={fid => patchChat(c.id, { folder_id: fid })}
        onDelete={() => deleteChat(c.id)}
        onDragStart={chatDragStart(c.id)}
      />
    );
  }

  return (
    <aside className="m3-sidebar">
      <header className="m3-sidebar__head">
        <button className="m3-sidebar__collapse" onClick={onToggleCollapsed} aria-label="Collapse">‹</button>
        <span className="m3-sidebar__title">Chats</span>
        <button className="m3-sidebar__newchat" onClick={onNewChat} title="New chat">＋</button>
      </header>

      <div className="m3-sidebar__scroll">
        {chats.length === 0 && (
          <div className="m3-sidebar__empty">Start a conversation to see it here.</div>
        )}

        {pinned.length > 0 && (
          <section className="m3-sidebar__section">
            <h4 className="m3-sidebar__section-title">Pinned</h4>
            {pinned.map(renderChat)}
          </section>
        )}

        <section className="m3-sidebar__section">
          <header className="m3-sidebar__section-head">
            <h4 className="m3-sidebar__section-title">Folders</h4>
            <button
              className="m3-sidebar__add-folder"
              onClick={() => { setCreatingFolder(true); setFolderDraft(""); }}
              aria-label="New folder"
              title="New folder"
            >＋</button>
          </header>
          {creatingFolder && (
            <input
              autoFocus
              className="m3-sidebar__new-folder-input"
              value={folderDraft}
              onChange={e => setFolderDraft(e.target.value)}
              placeholder="Folder name"
              onBlur={() => {
                const v = folderDraft.trim();
                if (v) createFolder(v);
                setCreatingFolder(false);
              }}
              onKeyDown={e => {
                if (e.key === "Enter") {
                  const v = folderDraft.trim();
                  if (v) createFolder(v);
                  setCreatingFolder(false);
                }
                if (e.key === "Escape") setCreatingFolder(false);
              }}
            />
          )}
          {folders.map(f => {
            const expanded = folderExpanded[f.id] !== false; // default expanded
            const items = byFolder.get(f.id) || [];
            return (
              <div key={f.id}>
                <FolderRow
                  folder={f}
                  childCount={items.length}
                  expanded={expanded}
                  onToggle={() => setFolderExpanded(s => ({ ...s, [f.id]: !expanded }))}
                  onRename={name => renameFolder(f.id, name)}
                  onDelete={() => deleteFolder(f.id)}
                  onDropChat={cid => patchChat(cid, { folder_id: f.id })}
                />
                {expanded && (
                  <div className="m3-sidebar__folder-children">
                    {items.length === 0
                      ? <div className="m3-sidebar__folder-empty">Drag chats here to organize.</div>
                      : items.map(renderChat)}
                  </div>
                )}
              </div>
            );
          })}
        </section>

        <section
          className="m3-sidebar__section"
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault();
            const cid = e.dataTransfer.getData("application/x-chat-id");
            if (cid) patchChat(cid, { folder_id: null });
          }}
        >
          <h4 className="m3-sidebar__section-title">Chats</h4>
          {BUCKET_ORDER.map(b => recency[b].length > 0 && (
            <div key={b}>
              <h5 className="m3-sidebar__bucket-label">{BUCKET_LABEL[b]}</h5>
              {recency[b].map(renderChat)}
            </div>
          ))}
        </section>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd client && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/canvas/ChatHistorySidebar.tsx
git commit -m "feat(sidebar): ChatHistorySidebar shell with read+mutation"
```

---

## Task 15: Frontend — wire sidebar into Canvas

**Files:**
- Modify: `client/src/views/Canvas.tsx`

- [ ] **Step 1: Add state for sidebar collapsed + refresh key**

Inside the `Canvas()` component, alongside the `activeSessionId` state from Task 10, add:

```typescript
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("m3-sidebar-collapsed") === "1";
  });
  useEffect(() => {
    localStorage.setItem("m3-sidebar-collapsed", sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  const [chatsRefreshKey, setChatsRefreshKey] = useState(0);
```

- [ ] **Step 2: Bump refresh key when a chat send completes**

Find the existing `onSend` callback or whatever wires `ChatRail`'s `onSend` to refetching the cluster. Add a refresh bump there. Concretely, locate the call to `ChatRail` and modify the prop:

```typescript
        onSend={(text) => {
          // existing cluster-refetch logic ...
          // After the round trip the agent will have minted/updated a session.
          // Bump after a short delay so the auto-title task has time to land.
          setTimeout(() => setChatsRefreshKey(k => k + 1), 1500);
        }}
```

If there's no inline `onSend` lambda yet (it's a separate function), add the line at the end of that function instead.

- [ ] **Step 3: Import the sidebar at the top of Canvas.tsx**

```typescript
import { ChatHistorySidebar } from "../components/canvas/ChatHistorySidebar";
```

- [ ] **Step 4: Render the sidebar**

In the JSX, immediately before `<ChatRail .../>`:

```tsx
      <ChatHistorySidebar
        activeSessionId={activeSessionId}
        onSelectSession={(sid) => setActiveSessionId(sid)}
        onNewChat={() => setActiveSessionId(null)}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(c => !c)}
        refreshKey={chatsRefreshKey}
      />
```

`onNewChat` simply nulls the active session id; `ChatRail`'s send loop will mint a new one lazily via `ensureSessionId`.

- [ ] **Step 5: Update wrapping layout**

Find the existing wrapper around `<ChatRail>` and `<Graph>`. It's likely a flex container. Make sure the sidebar sits as the first child so the row reads sidebar | rail | graph. Verify by reading the relevant JSX block. The CSS file (Task 16) handles widths.

- [ ] **Step 6: Type-check + visual smoke**

Run: `cd client && npx tsc --noEmit`
Then `npm run dev` and confirm three panes render. Expect ugly styling (Task 16 fixes that).

- [ ] **Step 7: Commit**

```bash
git add client/src/views/Canvas.tsx
git commit -m "feat(canvas): wire ChatHistorySidebar into the layout"
```

---

## Task 16: Frontend — sidebar CSS

**Files:**
- Modify: `client/src/index.css`

- [ ] **Step 1: Append the sidebar styles**

Add to the end of `client/src/index.css`. Match existing conventions (`m3-*` BEM-ish, the same neutral palette as `m3-chat-rail__*`). If the file uses CSS variables for colors elsewhere, prefer those — read the top of the file to find them and substitute.

```css
/* ------------------------------------------------------------------ */
/* Chat history sidebar                                               */
/* ------------------------------------------------------------------ */

.m3-sidebar {
  width: 260px;
  min-width: 260px;
  height: 100%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--m3-border, rgba(255,255,255,0.06));
  background: var(--m3-panel, rgba(20,20,24,0.6));
  color: var(--m3-fg, #e6e6ea);
  font-size: 12.5px;
}

.m3-sidebar--collapsed {
  width: 44px;
  min-width: 44px;
  align-items: center;
  padding-top: 10px;
  gap: 8px;
}

.m3-sidebar__head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--m3-border, rgba(255,255,255,0.06));
}

.m3-sidebar__title {
  font-weight: 600;
  flex: 1;
  letter-spacing: 0.02em;
  font-size: 12px;
  opacity: 0.9;
}

.m3-sidebar__collapse,
.m3-sidebar__expand,
.m3-sidebar__newchat,
.m3-sidebar__add-folder {
  background: transparent;
  border: 1px solid transparent;
  color: inherit;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  opacity: 0.7;
}
.m3-sidebar__collapse:hover,
.m3-sidebar__expand:hover,
.m3-sidebar__newchat:hover,
.m3-sidebar__add-folder:hover {
  opacity: 1;
  background: rgba(255,255,255,0.06);
}

.m3-sidebar__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 6px 6px 24px;
}

.m3-sidebar__empty {
  padding: 24px 12px;
  opacity: 0.5;
  text-align: center;
}

.m3-sidebar__section { margin-top: 12px; }
.m3-sidebar__section-head {
  display: flex; align-items: center; gap: 4px; padding: 0 8px;
}
.m3-sidebar__section-title {
  margin: 0; padding: 4px 8px;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: rgba(255,255,255,0.4); font-weight: 600; flex: 1;
}
.m3-sidebar__bucket-label {
  margin: 8px 0 2px; padding: 0 12px;
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em;
  color: rgba(255,255,255,0.3); font-weight: 600;
}
.m3-sidebar__folder-children { padding-left: 14px; }
.m3-sidebar__folder-empty {
  padding: 6px 14px; font-size: 11px; opacity: 0.4; font-style: italic;
}
.m3-sidebar__new-folder-input {
  width: calc(100% - 16px); margin: 4px 8px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  padding: 4px 8px; color: inherit; font: inherit;
}

/* Chat row */
.m3-chat-row {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 8px; margin: 1px 4px;
  border-radius: 6px; cursor: pointer;
  position: relative;
}
.m3-chat-row:hover { background: rgba(255,255,255,0.04); }
.m3-chat-row--active { background: rgba(120,140,255,0.14); }
.m3-chat-row--active:hover { background: rgba(120,140,255,0.18); }
.m3-chat-row__title {
  flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.m3-chat-row__rename {
  flex: 1; background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.16); border-radius: 4px;
  color: inherit; font: inherit; padding: 1px 4px;
}
.m3-chat-row__actions {
  display: none; gap: 2px;
}
.m3-chat-row:hover .m3-chat-row__actions,
.m3-chat-row--active .m3-chat-row__actions { display: inline-flex; }
.m3-chat-row__pin, .m3-chat-row__menu {
  background: transparent; border: none; color: inherit;
  width: 18px; height: 18px; line-height: 1;
  cursor: pointer; opacity: 0.5; border-radius: 3px;
  font-size: 13px;
}
.m3-chat-row__pin:hover, .m3-chat-row__menu:hover {
  opacity: 1; background: rgba(255,255,255,0.08);
}
.m3-chat-row__pin--on { opacity: 1; color: #f5b86b; }

/* Folder row */
.m3-folder-row {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 6px; margin: 1px 4px;
  border-radius: 6px; cursor: default;
}
.m3-folder-row:hover { background: rgba(255,255,255,0.03); }
.m3-folder-row--drop {
  background: rgba(120,140,255,0.18);
  outline: 1px dashed rgba(120,140,255,0.6);
}
.m3-folder-row__toggle {
  background: transparent; border: none; color: inherit;
  width: 16px; opacity: 0.6; cursor: pointer; font-size: 10px;
}
.m3-folder-row__name { flex: 1; font-weight: 500; }
.m3-folder-row__rename {
  flex: 1; background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.16); border-radius: 4px;
  color: inherit; font: inherit; padding: 1px 4px;
}
.m3-folder-row__count {
  font-size: 10px; opacity: 0.5;
  background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 8px;
}
.m3-folder-row__menu {
  background: transparent; border: none; color: inherit;
  width: 18px; height: 18px; opacity: 0; cursor: pointer; font-size: 13px;
}
.m3-folder-row:hover .m3-folder-row__menu { opacity: 0.6; }
.m3-folder-row__menu:hover { opacity: 1; }

/* Row menu popover */
.m3-row-menu {
  background: rgba(28,28,32,0.98);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 4px;
  min-width: 160px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  z-index: 1000;
  font-size: 12.5px;
}
.m3-row-menu__item {
  display: flex; align-items: center; gap: 6px;
  width: 100%; padding: 6px 10px; border-radius: 5px;
  background: transparent; border: none; color: inherit;
  cursor: pointer; text-align: left; font: inherit;
}
.m3-row-menu__item:hover { background: rgba(255,255,255,0.08); }
.m3-row-menu__item--danger { color: #ff7676; }
.m3-row-menu__divider { height: 1px; background: rgba(255,255,255,0.08); margin: 4px 0; }
.m3-row-menu__item--has-children { position: relative; }
.m3-row-menu__chevron { margin-left: auto; opacity: 0.5; font-size: 10px; }
.m3-row-menu__submenu {
  position: absolute; left: 100%; top: 0;
  background: rgba(28,28,32,0.98);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 4px; min-width: 160px;
  display: none;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
.m3-row-menu__item--has-children:hover .m3-row-menu__submenu { display: block; }
```

- [ ] **Step 2: Confirm the dev server hot-reloads the styles**

Run: `cd client && npm run dev`
Walk through the verification checklist below.

- [ ] **Step 3: Verification (manual)**

- [ ] Three panes render: sidebar, chat rail, canvas.
- [ ] Empty state shows when there are no chats.
- [ ] Send a chat: the row appears in the sidebar (initially with truncated user msg, then replaced by an LLM-generated title within ~2s).
- [ ] Reload the page: the rail still shows the chat, the sidebar shows the row, the row is highlighted as active.
- [ ] Click "+ New chat": rail clears, no row gets selected.
- [ ] Hover a row: pin star + ⋯ icon appear.
- [ ] Click pin: row jumps to a Pinned section at the top.
- [ ] Right-click a row → Rename: inline input appears, Enter commits, value sticks across reload, agent never overwrites.
- [ ] Right-click a row → Delete (and confirm): row gone, files gone from `~/brain/chats/`.
- [ ] Click "+ New folder", type a name, Enter: folder appears.
- [ ] Drag a chat row onto a folder header: chat moves into the folder.
- [ ] Drag a chat row onto the "Chats" section header: chat leaves the folder.
- [ ] Right-click folder → Delete (with chats inside): confirm prompt mentions chat count, chats orphan back into the recency list.
- [ ] Click ‹ on the sidebar header: collapses to 44px strip.
- [ ] Click › on the strip: expands.
- [ ] Reload while collapsed: stays collapsed.

- [ ] **Step 4: Commit**

```bash
git add client/src/index.css
git commit -m "style(sidebar): chat history sidebar styles"
```

---

## Task 17: End-to-end verification + cleanup commit

- [ ] **Step 1: Run full backend suite**

Run: `cd server && pytest`
Expected: PASS.

- [ ] **Step 2: Run frontend type check + build**

Run: `cd client && npx tsc --noEmit && npm run build`
Expected: clean build.

- [ ] **Step 3: Manual end-to-end pass**

Walk the verification checklist from Task 16 step 3 once more, top to bottom. Fix anything that drifted (e.g. a TS error introduced late, a CSS rule that shadowed an existing class).

- [ ] **Step 4: If a follow-up tweak was needed, commit it**

```bash
git add -p
git commit -m "fix(sidebar): <what>"
```

If nothing was needed, skip.

---

## Self-review (notes for the implementer)

- Optimistic updates revert via a full refetch on failure. Acceptable because failures are rare and the cost is one round-trip.
- Drag-and-drop uses the HTML5 API directly (no library) — minimal scope, matches the small surface area.
- Recency bucketing operates on `updated_at`. If you'd rather sort by `last_ts` (last assistant turn), trivially swap `c.updated_at` to `c.last_ts` inside `bucketFor` calls in Task 14 — they're typically the same value anyway because `append_turn` doesn't touch meta, but `write_meta` does bump updated_at, so renaming a chat will float it. That's actually desired (recent activity = renamed-recently counts).
- The auto-title routine is the one place where a backend failure is silent. That's a deliberate spec call ("never block the user"). If you find yourself debugging "title didn't update" — check `server/m3/brain/auto_title.py` log warnings.
