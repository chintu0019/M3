import uuid
from pathlib import Path

import pytest

from m3.brain.claims import ClaimMeta, write_claim
from m3.brain.entity_doc import EntityDoc, upsert
from m3.brain.synthesis import read_synthesis
from m3.core.synthesize import (
    MIN_CLAIMS_FOR_SYNTHESIS,
    stale_entity_slugs,
    synthesize_entity,
    synthesize_stale,
)


def _claim(item_id: uuid.UUID, prop: str, *, slug: str = "m3", confidence: float = 0.85) -> ClaimMeta:
    return ClaimMeta(
        id=uuid.uuid4(),
        item_id=item_id,
        proposition=prop,
        confidence=confidence,
        supporting_span=prop,
        entity_slugs=[slug],
        created_at="2026-05-08T10:00:00+00:00",
    )


def _seed_entity(brain_root: Path, slug: str = "m3", canonical: str = "M3") -> None:
    upsert(brain_root, EntityDoc(
        canonical_name=canonical, entity_type="project", aliases=[], description=None,
        related=[], signal_mentions=0, summary_external=None, body="",
    ))


def _seed_claims(brain_root: Path, n: int, *, slug: str = "m3") -> list[ClaimMeta]:
    item_id = uuid.uuid4()
    claims = [_claim(item_id, f"Claim number {i} about {slug}.", slug=slug) for i in range(n)]
    for c in claims:
        write_claim(brain_root, c)
    return claims


@pytest.mark.asyncio
async def test_synthesize_skips_when_too_few_claims(tmp_brain: Path, fake_llm):
    _seed_entity(tmp_brain)
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS - 1)
    result = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm)
    assert not result.written
    assert "claims" in (result.skipped_reason or "")
    assert read_synthesis(tmp_brain, "m3") is None


@pytest.mark.asyncio
async def test_synthesize_writes_when_enough_claims(tmp_brain: Path, fake_llm):
    _seed_entity(tmp_brain)
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS)

    fake_llm.set_response("Claims about M3", {
        "summary": "M3 is local-first and minimal.",
        "tensions": ["Some claims hint at sync; others reject it."],
    })

    result = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm)
    assert result.written
    assert result.meta is not None
    assert result.meta.summary == "M3 is local-first and minimal."
    assert len(result.meta.tensions) == 1

    loaded = read_synthesis(tmp_brain, "m3")
    assert loaded is not None
    assert loaded.summary == "M3 is local-first and minimal."


@pytest.mark.asyncio
async def test_synthesize_skips_when_up_to_date(tmp_brain: Path, fake_llm):
    _seed_entity(tmp_brain)
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS)
    fake_llm.set_response("Claims about M3", {
        "summary": "Initial summary.", "tensions": [],
    })
    first = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm)
    assert first.written

    # No new claims; second pass should no-op.
    second = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm)
    assert not second.written
    assert second.skipped_reason == "up to date"


@pytest.mark.asyncio
async def test_synthesize_force_regenerates(tmp_brain: Path, fake_llm):
    _seed_entity(tmp_brain)
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS)
    fake_llm.set_response("Claims about M3", {"summary": "first version.", "tensions": []})
    first = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm)
    assert first.written

    fake_llm.set_response("Claims about M3", {"summary": "second version.", "tensions": []})
    second = await synthesize_entity(brain_root=tmp_brain, entity_slug="m3", llm=fake_llm, force=True)
    assert second.written
    assert second.meta is not None
    assert second.meta.summary == "second version."


@pytest.mark.asyncio
async def test_stale_entity_slugs_omits_entities_below_min(tmp_brain: Path):
    _seed_entity(tmp_brain, slug="thin", canonical="Thin")
    _seed_claims(tmp_brain, 1, slug="thin")
    _seed_entity(tmp_brain, slug="thick", canonical="Thick")
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS, slug="thick")

    assert stale_entity_slugs(tmp_brain) == ["thick"]


@pytest.mark.asyncio
async def test_synthesize_stale_runs_each_pending(tmp_brain: Path, fake_llm):
    _seed_entity(tmp_brain, slug="a", canonical="A")
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS, slug="a")
    _seed_entity(tmp_brain, slug="b", canonical="B")
    _seed_claims(tmp_brain, MIN_CLAIMS_FOR_SYNTHESIS, slug="b")

    fake_llm.set_response("Claims about A", {"summary": "Summary for A.", "tensions": []})
    fake_llm.set_response("Claims about B", {"summary": "Summary for B.", "tensions": []})

    results = await synthesize_stale(brain_root=tmp_brain, llm=fake_llm)
    assert len(results) == 2
    assert all(r.written for r in results)
    assert {r.entity_slug for r in results} == {"a", "b"}
