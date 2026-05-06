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
