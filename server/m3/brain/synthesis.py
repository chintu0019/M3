"""Synthesis storage: one synthesized note per entity, distilled from its claims.

A synthesis is a *second-order* artifact: while a claim is one proposition
extracted from a single item, a synthesis pulls together every claim about an
entity and asks the LLM "what do these collectively say, and where do they
disagree?" This is the layer the user actually navigates by — the
hand-curated wiki note Karpathy keeps for himself, but generated.

Storage shape:

    ~/brain/syntheses/<entity_slug>.md

JSON frontmatter (consistent with claims.py) + a markdown body. One file per
entity; regeneration replaces it. Git history is the version log.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from m3.brain.layout import BrainPaths


@dataclass
class SynthesisMeta:
    id: uuid.UUID
    entity_slug: str
    summary: str                                  # 1–3 sentence distillation
    tensions: list[str] = field(default_factory=list)   # 0–3 contradictions / open threads
    claim_ids: list[uuid.UUID] = field(default_factory=list)
    generated_at: str = ""                        # ISO8601 UTC
    model_label: str = ""                         # provider/model that generated it


def _serialize_frontmatter(meta: SynthesisMeta) -> str:
    payload = asdict(meta)
    payload["id"] = str(meta.id)
    payload["claim_ids"] = [str(cid) for cid in meta.claim_ids]
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


def _format_body(meta: SynthesisMeta) -> str:
    parts = [meta.summary.strip()]
    if meta.tensions:
        parts.append("")
        parts.append("## Tensions")
        for t in meta.tensions:
            parts.append(f"- {t.strip()}")
    return "\n".join(parts) + "\n"


def write_synthesis(root: Path, meta: SynthesisMeta) -> Path:
    p = BrainPaths(root)
    p.syntheses_dir.mkdir(parents=True, exist_ok=True)
    target = p.syntheses_dir / f"{meta.entity_slug}.md"
    body = (
        "---\n"
        + _serialize_frontmatter(meta)
        + "\n---\n\n"
        + _format_body(meta)
    )
    target.write_text(body)
    return target


def read_synthesis(root: Path, entity_slug: str) -> SynthesisMeta | None:
    p = BrainPaths(root)
    target = p.syntheses_dir / f"{entity_slug}.md"
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
        data["claim_ids"] = [uuid.UUID(cid) for cid in data.get("claim_ids", [])]
    except (KeyError, ValueError):
        return None
    known = {f for f in SynthesisMeta.__dataclass_fields__}
    return SynthesisMeta(**{k: v for k, v in data.items() if k in known})


def iter_syntheses(root: Path):
    """Yield every persisted SynthesisMeta in arbitrary order."""
    p = BrainPaths(root)
    if not p.syntheses_dir.exists():
        return
    for path in p.syntheses_dir.glob("*.md"):
        slug = path.stem
        meta = read_synthesis(root, slug)
        if meta is not None:
            yield meta


def is_stale(synthesis: SynthesisMeta, current_claim_ids: set[uuid.UUID], *, delta_threshold: int = 3) -> bool:
    """A synthesis is stale when the entity has accumulated `delta_threshold`+
    new claims since it was last generated, OR when claims have been removed.

    Used by the synthesis driver to decide whether to spend an LLM call
    regenerating an entity's synthesis.
    """
    indexed = set(synthesis.claim_ids)
    added = current_claim_ids - indexed
    removed = indexed - current_claim_ids
    return len(added) >= delta_threshold or len(removed) > 0
