"""Structured record files: one JSON per receipt/bill/ticket."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from m3.brain.entity_doc import slugify
from m3.brain.layout import BrainPaths


@dataclass
class Record:
    item_id: uuid.UUID
    amount: float
    currency: str
    vendor: str
    date: str                   # YYYY-MM-DD
    category: str
    due_date: str | None
    reference_id: str | None


def write_record(root: Path, rec: Record) -> Path:
    p = BrainPaths(root)
    slug = slugify(rec.vendor)
    path = p.records_dir / f"{rec.date}-{slug}.json"
    data = asdict(rec)
    data["item_id"] = str(rec.item_id)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path
