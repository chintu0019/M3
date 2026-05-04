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
    return ItemMeta(**data)
