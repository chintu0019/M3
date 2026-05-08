import uuid
from pathlib import Path

from m3.brain.synthesis import (
    SynthesisMeta,
    is_stale,
    iter_syntheses,
    read_synthesis,
    write_synthesis,
)


def _meta(slug: str = "m3", *, claim_ids: list[uuid.UUID] | None = None) -> SynthesisMeta:
    return SynthesisMeta(
        id=uuid.uuid4(),
        entity_slug=slug,
        summary="M3 is local-first; the user values portability.",
        tensions=["Some claims push for cloud sync; recent claims push back."],
        claim_ids=claim_ids or [uuid.uuid4(), uuid.uuid4()],
        generated_at="2026-05-08T10:00:00+00:00",
        model_label="anthropic/claude-opus-4-7",
    )


def test_write_then_read_roundtrip(tmp_brain: Path):
    meta = _meta()
    write_synthesis(tmp_brain, meta)
    loaded = read_synthesis(tmp_brain, meta.entity_slug)
    assert loaded == meta


def test_body_renders_summary_and_tensions_for_grep(tmp_brain: Path):
    meta = _meta()
    path = write_synthesis(tmp_brain, meta)
    text = path.read_text()
    assert meta.summary in text
    assert "## Tensions" in text
    assert meta.tensions[0] in text


def test_iter_syntheses_yields_each(tmp_brain: Path):
    a = _meta(slug="m3")
    b = _meta(slug="pilot-path")
    write_synthesis(tmp_brain, a)
    write_synthesis(tmp_brain, b)
    seen = {s.entity_slug for s in iter_syntheses(tmp_brain)}
    assert seen == {"m3", "pilot-path"}


def test_write_replaces_previous_synthesis_for_same_entity(tmp_brain: Path):
    first = _meta(slug="m3")
    write_synthesis(tmp_brain, first)
    second = SynthesisMeta(
        id=uuid.uuid4(),
        entity_slug="m3",
        summary="Updated distillation.",
        tensions=[],
        claim_ids=[uuid.uuid4()],
        generated_at="2026-05-09T10:00:00+00:00",
    )
    write_synthesis(tmp_brain, second)

    loaded = read_synthesis(tmp_brain, "m3")
    assert loaded is not None
    assert loaded.summary == "Updated distillation."
    assert loaded.id == second.id


def test_is_stale_when_threshold_new_claims_added():
    base = [uuid.uuid4() for _ in range(2)]
    meta = _meta(claim_ids=base)
    extra = {uuid.uuid4() for _ in range(3)}
    assert is_stale(meta, set(base) | extra, delta_threshold=3)


def test_is_stale_when_a_claim_is_removed():
    base = [uuid.uuid4() for _ in range(4)]
    meta = _meta(claim_ids=base)
    smaller = set(base[:-1])
    assert is_stale(meta, smaller, delta_threshold=10)


def test_is_not_stale_when_within_threshold():
    base = [uuid.uuid4() for _ in range(4)]
    meta = _meta(claim_ids=base)
    plus_two = set(base) | {uuid.uuid4(), uuid.uuid4()}
    assert not is_stale(meta, plus_two, delta_threshold=3)


def test_read_synthesis_missing_returns_none(tmp_brain: Path):
    assert read_synthesis(tmp_brain, "nonexistent") is None
