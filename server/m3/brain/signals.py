"""Signals log: light-touch ingests that don't deserve a full entity page."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from m3.brain.entity_doc import load, slugify, upsert
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


def _mentions_path(root: Path) -> Path:
    return BrainPaths(root).index_dir / "signal_mentions.json"


def _load_mentions(root: Path) -> dict:
    path = _mentions_path(root)
    if not path.exists():
        return {"mentions": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"mentions": {}}
    if "mentions" not in data or not isinstance(data["mentions"], dict):
        data["mentions"] = {}
    return data


def _save_mentions(root: Path, data: dict) -> None:
    path = _mentions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def bump_mention_count(
    root: Path,
    *,
    canonical_name: str,
    takeaway: str | None = None,
    date: str | None = None,
) -> int:
    """Increment the signal-mention counter for ``canonical_name``.

    - Counter is persisted at ``index/signal_mentions.json`` regardless of whether an
      entity page exists for this name.
    - If an entity page DOES exist for ``slugify(canonical_name)``, its
      ``signal_mentions`` frontmatter value is also bumped.
    - If no entity exists, we do NOT create a stub page. The counter is the only
      persistent side effect. This keeps news-article ingests from spawning entity
      files (see spec §14.7).

    Returns the new counter value from the JSON store.
    """
    data = _load_mentions(root)
    mentions: dict = data["mentions"]
    entry = mentions.get(canonical_name) or {"count": 0, "last_seen": None, "takeaways": []}
    entry["count"] = int(entry.get("count") or 0) + 1
    if date is not None:
        entry["last_seen"] = date
    if takeaway:
        takeaways = list(entry.get("takeaways") or [])
        takeaways.append(takeaway)
        entry["takeaways"] = takeaways
    mentions[canonical_name] = entry
    data["mentions"] = mentions
    _save_mentions(root, data)

    existing = load(root, slug=slugify(canonical_name))
    if existing is not None:
        existing.signal_mentions += 1
        upsert(root, existing)

    return entry["count"]
