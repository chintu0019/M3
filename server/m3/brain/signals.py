"""Signals log: light-touch ingests that don't deserve a full entity page."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from m3.brain.entity_doc import EntityDoc, load, slugify, upsert
from m3.brain.layout import BrainPaths


@dataclass
class Signal:
    item_id: uuid.UUID
    date: str                   # YYYY-MM-DD
    topic_entities: list[str]   # canonical names (may or may not match existing)
    one_line_takeaway: str


def append_signal(root: Path, sig: Signal) -> Path:
    p = BrainPaths(root)
    month = sig.date[:7]         # YYYY-MM
    path = p.signals_dir / f"{month}.md"
    if not path.exists():
        path.write_text(f"# Signals — {month}\n\n")
    topics = ", ".join(sig.topic_entities) if sig.topic_entities else "(no topics)"
    line = f"- {sig.date} — [{topics}] {sig.one_line_takeaway} (item: {sig.item_id})\n"
    with path.open("a") as fh:
        fh.write(line)
    return path


def bump_mention_count(root: Path, *, canonical_name: str) -> int:
    """Increment signal_mentions on the entity. Create a stub if missing. Returns new count."""
    slug = slugify(canonical_name)
    existing = load(root, slug=slug)
    if existing is None:
        doc = EntityDoc(
            canonical_name=canonical_name, entity_type="topic",
            aliases=[], description=None, related=[], signal_mentions=1,
            summary_external=None, body="",
        )
        upsert(root, doc)
        return 1
    existing.signal_mentions += 1
    upsert(root, existing)
    return existing.signal_mentions
