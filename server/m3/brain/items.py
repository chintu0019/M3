"""Item storage: originals go in items/originals/, metadata sidecars in items/meta/."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from m3.brain.layout import BrainPaths


@dataclass
class ItemMeta:
    id: uuid.UUID
    kind: str                           # personal | reference | record | signal
    source: str                         # telegram | share_sheet | drag_drop | cli | ...
    created_at: str                     # ISO8601 UTC
    original_filename: str | None
    extracted_text: str
    when_iso: str | None
    when_source: str                    # explicit_in_content | inferred_from_metadata | ingest_time | unknown
    hooks: dict[str, Any]
    llm_output_raw: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    archived: bool = False


def write_item(root: Path, item_id: uuid.UUID, *, extension: str, content: bytes) -> Path:
    p = BrainPaths(root)
    target = p.items_originals / f"{item_id}.{extension.lstrip('.')}"
    target.write_bytes(content)
    return target


def write_meta(root: Path, meta: ItemMeta) -> Path:
    p = BrainPaths(root)
    target = p.items_meta / f"{meta.id}.json"
    data = asdict(meta)
    data["id"] = str(meta.id)
    target.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return target


def read_meta(root: Path, item_id: uuid.UUID) -> ItemMeta | None:
    p = BrainPaths(root)
    target = p.items_meta / f"{item_id}.json"
    if not target.exists():
        return None
    data = json.loads(target.read_text())
    data["id"] = uuid.UUID(data["id"])
    # Tolerate older meta JSONs that predate fields like `archived` — let
    # dataclass defaults fill them in instead of crashing the loader.
    known = {f for f in ItemMeta.__dataclass_fields__}
    return ItemMeta(**{k: v for k, v in data.items() if k in known})


def iter_metas(root: Path):
    """Yield every persisted ItemMeta in arbitrary order. Used by listing/index callers."""
    p = BrainPaths(root)
    if not p.items_meta.exists():
        return
    for path in p.items_meta.glob("*.json"):
        try:
            uid = uuid.UUID(path.stem)
        except ValueError:
            continue
        meta = read_meta(root, uid)
        if meta is not None:
            yield meta
