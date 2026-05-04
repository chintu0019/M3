"""Walk ~/brain/items/meta/*.json and (re)populate FTS + hooks + vectors.

Used by `m3 reindex` CLI (P2) and by cold-start flows that import raw items
from an external source and need the derived indexes to exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from m3.brain.fts import FTSIndex
from m3.brain.hooks import HookIndex
from m3.brain.items import read_meta
from m3.brain.layout import BrainPaths
from m3.brain.vectors import VectorIndex


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ReindexResult:
    items_indexed: int
    errors: list[str]


async def reindex_all(root: Path, *, embedder: _Embedder) -> ReindexResult:
    p = BrainPaths(root)
    errors: list[str] = []
    count = 0
    fidx = FTSIndex.open(root)
    hidx = HookIndex.open(root)
    vidx = VectorIndex.open(root)
    try:
        for meta_path in sorted(p.items_meta.glob("*.json")):
            try:
                item_id = uuid.UUID(meta_path.stem)
            except ValueError:
                errors.append(f"bad meta filename: {meta_path.name}")
                continue
            meta = read_meta(root, item_id)
            if meta is None:
                errors.append(f"read_meta returned None for {item_id}")
                continue
            if meta.extracted_text:
                fidx.upsert_item(item_id=str(item_id), text=meta.extracted_text)
                try:
                    vec = (await embedder.embed([meta.extracted_text]))[0]
                    vidx.upsert_item(item_id=str(item_id), embedding=vec)
                except Exception as e:
                    errors.append(f"embed failed for {item_id}: {e}")

            hooks = meta.hooks or {}
            hidx.upsert_item_hooks(
                item_id=str(item_id),
                who=[_ref_name(r) for r in (hooks.get("who") or [])],
                what=[_ref_name(r) for r in (hooks.get("what") or [])],
                where=[_ref_name(r) for r in (hooks.get("where") or [])],
                project=[str(p) for p in (hooks.get("project") or []) if p],
                stance_entities=[(s.get("entity_name") or "") for s in (hooks.get("stance") or []) if isinstance(s, dict)],
            )
            count += 1
    finally:
        fidx.close()
        hidx.close()
        vidx.close()
    return ReindexResult(items_indexed=count, errors=errors)


def _ref_name(ref) -> str:
    if isinstance(ref, dict):
        return (ref.get("name") or "").strip()
    if isinstance(ref, str):
        return ref.strip()
    return ""
