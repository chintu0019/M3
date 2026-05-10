"""Claim storage: per-item atomic propositions extracted by the LLM.

Each claim is a single-sentence proposition (e.g. "M3 chose markdown over a
relational store because the user wanted local-first portability") with a
supporting quote, a confidence, and the entities it's about. Claims are the
synthesis layer above raw items — they're what the canvas surfaces as nodes,
not the raw uploaded files.

Storage shape:

    ~/brain/claims/<uuid>.md

with YAML frontmatter and the proposition as the body. Markdown so it stays
greppable + diffable in the brain repo, mirroring entity_doc.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from m3.brain.layout import BrainPaths


@dataclass
class ClaimMeta:
    id: uuid.UUID
    item_id: uuid.UUID
    proposition: str
    confidence: float
    supporting_span: str
    headline: str = ""              # 3-7 word interpretive label for the canvas v2 layout
    entity_slugs: list[str] = field(default_factory=list)
    created_at: str = ""              # ISO8601 UTC


def _serialize_frontmatter(meta: ClaimMeta) -> str:
    payload = asdict(meta)
    payload["id"] = str(meta.id)
    payload["item_id"] = str(meta.item_id)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def write_claim(root: Path, meta: ClaimMeta) -> Path:
    p = BrainPaths(root)
    p.claims_dir.mkdir(parents=True, exist_ok=True)
    target = p.claims_dir / f"{meta.id}.md"
    body = (
        "---\n"
        + _serialize_frontmatter(meta)
        + "\n---\n\n"
        + meta.proposition.strip()
        + "\n"
    )
    target.write_text(body)
    return target


def read_claim(root: Path, claim_id: uuid.UUID) -> ClaimMeta | None:
    p = BrainPaths(root)
    target = p.claims_dir / f"{claim_id}.md"
    if not target.exists():
        return None
    text = target.read_text()
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    raw = text[4:end]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        data["id"] = uuid.UUID(data["id"])
        data["item_id"] = uuid.UUID(data["item_id"])
    except (KeyError, ValueError):
        return None
    known = {f for f in ClaimMeta.__dataclass_fields__}
    return ClaimMeta(**{k: v for k, v in data.items() if k in known})


def iter_claims(root: Path):
    """Yield every persisted ClaimMeta in arbitrary order."""
    p = BrainPaths(root)
    if not p.claims_dir.exists():
        return
    for path in p.claims_dir.glob("*.md"):
        try:
            cid = uuid.UUID(path.stem)
        except ValueError:
            continue
        claim = read_claim(root, cid)
        if claim is not None:
            yield claim


def claims_for_item(root: Path, item_id: uuid.UUID) -> list[ClaimMeta]:
    """All claims that cite a particular item. O(N) over the claims dir; fine
    until the user has thousands of items, at which point we'd add a sqlite index."""
    return [c for c in iter_claims(root) if c.item_id == item_id]


def delete_claims_for_item(root: Path, item_id: uuid.UUID) -> list[uuid.UUID]:
    """Remove every claim whose source is `item_id`. Returns the ids removed.

    Used by the reprocess path so a re-extraction doesn't pile new claims on
    top of stale ones from the previous run.
    """
    p = BrainPaths(root)
    removed: list[uuid.UUID] = []
    for claim in claims_for_item(root, item_id):
        path = p.claims_dir / f"{claim.id}.md"
        if path.exists():
            path.unlink()
        removed.append(claim.id)
    return removed
