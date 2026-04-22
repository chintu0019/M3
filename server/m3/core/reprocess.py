"""Re-run extraction on existing items without re-ingesting source material.

When the extraction prompt or model improves, items already stored under
``~/brain/items/meta/`` still carry their old ``llm_output_raw`` and the
derived self/entity pages reflect those older extractions. The functions
here replay items through the current pipeline so those improvements land
without re-uploading source material.

Three entry points:

- :func:`reprocess_one` — re-run a single item. Leaves prior self/entity
  state in place; callers accept that re-ingestion may duplicate some
  content (``self_doc.apply_update`` and ``entity_doc.upsert`` are only
  idempotent for ``append`` when content matches exactly).
- :func:`reprocess_all_unknown` — re-extract only items where
  ``kind == "unknown"`` (the graceful-degradation fallback path).
- :func:`reprocess_all` — nuclear option. Wipes all derived state
  (entities, records, signals, index, self.md, open_questions.md,
  changelog.md) and replays every item in chronological order. Items
  themselves (originals + meta) are preserved.
"""

from __future__ import annotations

import shutil
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from m3.brain.items import ItemMeta, read_meta
from m3.brain.layout import BrainPaths, init_brain
from m3.core.ingest import IngestInput, Ingester
from m3.core.llm import LLMProvider


class _Embedder(Protocol):
    dim: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class ReprocessResult:
    items_processed: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _meta_to_ingest_input(meta: ItemMeta) -> IngestInput:
    """Feed the already-extracted text back into the Ingester.

    We skip the bytes round-trip because the text is already in the meta
    file — running extractors again on the original bytes would just
    reproduce the same text at best, and fail on missing originals at worst.
    """
    return IngestInput(
        item_id=meta.id,
        source=meta.source,
        original_bytes=None,
        original_filename=meta.original_filename,
        content_type="text",
        text=meta.extracted_text,
        user_notes=None,
    )


async def reprocess_one(
    *,
    brain_root: Path,
    item_id: _uuid.UUID,
    llm: LLMProvider,
    embedder: _Embedder,
) -> ReprocessResult:
    """Re-extract one item against the current prompt/model.

    Known limitation: prior self/entity state from the first ingest is not
    wiped. Re-ingestion may therefore duplicate some content. Users who
    want a clean slate should use :func:`reprocess_all`.
    """
    meta = read_meta(brain_root, item_id)
    if meta is None:
        return ReprocessResult(
            items_processed=0,
            items_skipped=1,
            errors=[f"item {item_id} not found"],
        )
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=embedder)
    try:
        await ingester.ingest(_meta_to_ingest_input(meta))
        return ReprocessResult(items_processed=1)
    except Exception as e:  # noqa: BLE001 — we surface all errors
        return ReprocessResult(
            items_processed=0,
            items_skipped=1,
            errors=[f"{item_id}: {e}"],
        )


async def reprocess_all_unknown(
    *,
    brain_root: Path,
    llm: LLMProvider,
    embedder: _Embedder,
) -> ReprocessResult:
    """Re-extract only items that landed in the ``kind == "unknown"`` fallback."""
    p = BrainPaths(brain_root)
    result = ReprocessResult()
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=embedder)
    for meta_path in sorted(p.items_meta.glob("*.json")):
        try:
            item_id = _uuid.UUID(meta_path.stem)
        except ValueError:
            result.errors.append(f"bad meta filename: {meta_path.name}")
            continue
        meta = read_meta(brain_root, item_id)
        if meta is None or meta.kind != "unknown":
            result.items_skipped += 1
            continue
        try:
            await ingester.ingest(_meta_to_ingest_input(meta))
            result.items_processed += 1
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"{item_id}: {e}")
            result.items_skipped += 1
    return result


async def reprocess_all(
    *,
    brain_root: Path,
    llm: LLMProvider,
    embedder: _Embedder,
) -> ReprocessResult:
    """Wipe all derived state and replay every item in chronological order.

    Preserved: ``items/originals/``, ``items/meta/``, ``config.yml``, and
    the ``.git`` directory. Everything else under the brain root is
    reconstructed from scratch by replaying each item through the
    Ingester, in ``created_at`` order.
    """
    p = BrainPaths(brain_root)
    result = ReprocessResult()

    # 1. Wipe derived directories. Keep items/ and anything else not listed.
    for name in ("entities", "records", "signals", "index"):
        target = brain_root / name
        if target.exists():
            shutil.rmtree(target)
    # Reset the top-level derived files so init_brain rewrites them fresh
    # (init_brain is idempotent on existing files, so we must unlink first).
    for f in (p.self_md, p.open_questions, p.changelog):
        if f.exists():
            f.unlink()
    init_brain(brain_root)

    # 2. Collect + sort metas by created_at.
    metas: list[ItemMeta] = []
    for meta_path in sorted(p.items_meta.glob("*.json")):
        try:
            item_id = _uuid.UUID(meta_path.stem)
        except ValueError:
            result.errors.append(f"bad meta filename: {meta_path.name}")
            continue
        meta = read_meta(brain_root, item_id)
        if meta is None:
            result.errors.append(f"read_meta returned None for {item_id}")
            continue
        metas.append(meta)
    metas.sort(key=lambda m: m.created_at)

    # 3. Replay.
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=embedder)
    for meta in metas:
        try:
            await ingester.ingest(_meta_to_ingest_input(meta))
            result.items_processed += 1
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"{meta.id}: {e}")
            result.items_skipped += 1
    return result
