"""Per-entity synthesis: roll up every claim about an entity into a single
1–3 sentence distillation plus 0–3 tensions.

This is the layer above claims — what the canvas wants to surface as the
Karpathy-style wiki note. Claims are atomic propositions extracted from
single items; a synthesis answers "what do all of these together actually
say about <entity>, and where do they pull in different directions?"

Not all entities deserve a synthesis: we gate on a minimum claim count
(`MIN_CLAIMS_FOR_SYNTHESIS`) so we don't burn LLM calls on entities that
only have one or two propositions attached.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from m3.brain.claims import ClaimMeta, iter_claims
from m3.brain.entity_doc import load as load_entity
from m3.brain.layout import BrainPaths
from m3.brain.synthesis import (
    SynthesisMeta,
    is_stale,
    iter_syntheses,
    read_synthesis,
    write_synthesis,
)
from m3.core.llm import LLMProvider, Tool

logger = logging.getLogger("m3.synthesize")

MIN_CLAIMS_FOR_SYNTHESIS = 3
DEFAULT_DELTA_THRESHOLD = 3


class _SynthOut(BaseModel):
    summary: str = Field(min_length=4, max_length=600)
    tensions: list[str] = Field(default_factory=list, max_length=3)


def _build_synth_prompt(entity_label: str, entity_type: str | None) -> str:
    type_str = entity_type or "topic"
    return (
        "You are M3's synthesis engine. You receive every claim a single user has "
        "captured about one entity. Your job is to distill them into a coherent note.\n\n"
        f"Entity: {entity_label!r} (type: {type_str})\n\n"
        "Output a `summary` (1–3 sentences capturing the through-line — what does "
        "this set of claims collectively say about the entity, in the user's own world?) "
        "and `tensions` (0–3 short bullets flagging contradictions, ambiguities, or "
        "open threads across the claims — only emit a tension if claims actually "
        "disagree or pull in different directions; otherwise return []).\n\n"
        "Rules:\n"
        "- The summary is FROM the user's perspective. They captured these claims "
        "  for a reason; reflect what's actually there, not encyclopedic facts.\n"
        "- Don't fabricate. If five claims all say the same thing, the summary is "
        "  one sentence. Resist filler.\n"
        "- Each tension cites the contradiction in plain language ('older claims "
        "  call X a priority, recent claims question that').\n"
        "- No quotation marks around the entity name in the summary."
    )


def _format_claim_for_prompt(claim: ClaimMeta) -> str:
    quote = f" — \"{claim.supporting_span}\"" if claim.supporting_span else ""
    return f"- (conf={claim.confidence:.2f}) {claim.proposition}{quote}"


def _synth_tool() -> Tool:
    return Tool(
        name="emit_synthesis",
        description="Emit a synthesis distilled from the provided claims.",
        input_schema=_SynthOut.model_json_schema(),
    )


@dataclass
class SynthesisResult:
    entity_slug: str
    written: bool
    skipped_reason: str | None = None
    meta: SynthesisMeta | None = None


async def synthesize_entity(
    *,
    brain_root: Path,
    entity_slug: str,
    llm: LLMProvider,
    model_label: str = "",
    force: bool = False,
) -> SynthesisResult:
    """Generate (or regenerate) the synthesis for one entity.

    No-ops when:
    - the entity has fewer than MIN_CLAIMS_FOR_SYNTHESIS attached claims, OR
    - a synthesis already exists and isn't stale (unless `force=True`).
    """
    claims = [c for c in iter_claims(brain_root) if entity_slug in c.entity_slugs]
    if len(claims) < MIN_CLAIMS_FOR_SYNTHESIS:
        return SynthesisResult(entity_slug, written=False,
                               skipped_reason=f"only {len(claims)} claims; need {MIN_CLAIMS_FOR_SYNTHESIS}")

    current_ids = {c.id for c in claims}
    existing = read_synthesis(brain_root, entity_slug)
    if existing is not None and not force and not is_stale(existing, current_ids):
        return SynthesisResult(entity_slug, written=False,
                               skipped_reason="up to date")

    doc = load_entity(brain_root, slug=entity_slug)
    label = doc.canonical_name if doc else entity_slug.replace("-", " ")
    etype = doc.entity_type if doc else None

    system = _build_synth_prompt(label, etype)
    # Stable order so cache hits work for unchanged claim sets.
    claims_sorted = sorted(claims, key=lambda c: (c.created_at, str(c.id)))
    user_msg = (
        f"Claims about {label} ({len(claims_sorted)}):\n\n"
        + "\n".join(_format_claim_for_prompt(c) for c in claims_sorted)
    )

    if not getattr(llm, "supports_tools", False):
        return SynthesisResult(entity_slug, written=False,
                               skipped_reason="llm does not support tool use")

    try:
        result = await llm.complete_tool(
            messages=[{"role": "user", "content": user_msg}],
            tools=[_synth_tool()],
            system=system,
            tool_choice="emit_synthesis",
            max_tokens=1024,
            temperature=0.2,
        )
        parsed = _SynthOut.model_validate(result.input or {})
    except ValidationError as e:
        logger.warning("synthesize %s: validation failed: %s", entity_slug, e)
        return SynthesisResult(entity_slug, written=False, skipped_reason=f"invalid output: {e}")

    meta = SynthesisMeta(
        id=uuid.uuid4(),
        entity_slug=entity_slug,
        summary=parsed.summary.strip(),
        tensions=[t.strip() for t in parsed.tensions if t.strip()],
        claim_ids=[c.id for c in claims_sorted],
        generated_at=datetime.now(timezone.utc).isoformat(),
        model_label=model_label,
    )
    write_synthesis(brain_root, meta)
    return SynthesisResult(entity_slug, written=True, meta=meta)


def stale_entity_slugs(brain_root: Path, *, delta_threshold: int = DEFAULT_DELTA_THRESHOLD) -> list[str]:
    """Return slugs of entities whose synthesis is missing or stale.

    Includes entities with no synthesis yet, provided they have at least
    MIN_CLAIMS_FOR_SYNTHESIS claims attached.
    """
    by_entity: dict[str, set[uuid.UUID]] = {}
    for c in iter_claims(brain_root):
        for slug in c.entity_slugs:
            by_entity.setdefault(slug, set()).add(c.id)

    out: list[str] = []
    existing = {s.entity_slug: s for s in iter_syntheses(brain_root)}
    for slug, claim_ids in by_entity.items():
        if len(claim_ids) < MIN_CLAIMS_FOR_SYNTHESIS:
            continue
        synth = existing.get(slug)
        if synth is None:
            out.append(slug)
            continue
        if is_stale(synth, claim_ids, delta_threshold=delta_threshold):
            out.append(slug)
    return out


async def synthesize_stale(
    *,
    brain_root: Path,
    llm: LLMProvider,
    model_label: str = "",
    delta_threshold: int = DEFAULT_DELTA_THRESHOLD,
    limit: int | None = None,
) -> list[SynthesisResult]:
    """Run synthesis for every stale entity. Used by the CLI / post-ingest hook.

    `limit` caps the number of entities synthesized in one pass so a huge
    backfill doesn't lock up the ingest pipeline; the caller can loop.
    """
    slugs = stale_entity_slugs(brain_root, delta_threshold=delta_threshold)
    if limit is not None:
        slugs = slugs[:limit]
    results: list[SynthesisResult] = []
    for slug in slugs:
        results.append(await synthesize_entity(
            brain_root=brain_root, entity_slug=slug, llm=llm, model_label=model_label,
        ))
    return results


# Re-exported so callers don't have to remember the BrainPaths plumbing.
def _claims_dir(root: Path) -> Path:
    return BrainPaths(root).claims_dir


__all__ = [
    "MIN_CLAIMS_FOR_SYNTHESIS",
    "DEFAULT_DELTA_THRESHOLD",
    "SynthesisResult",
    "synthesize_entity",
    "synthesize_stale",
    "stale_entity_slugs",
]
