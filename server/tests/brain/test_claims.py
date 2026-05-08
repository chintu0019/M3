import uuid
from pathlib import Path

from m3.brain.claims import (
    ClaimMeta,
    claims_for_item,
    delete_claims_for_item,
    iter_claims,
    read_claim,
    write_claim,
)


def _make_claim(item_id: uuid.UUID, *, prop: str = "X is true.", confidence: float = 0.8) -> ClaimMeta:
    return ClaimMeta(
        id=uuid.uuid4(),
        item_id=item_id,
        proposition=prop,
        confidence=confidence,
        supporting_span="X is the answer.",
        entity_slugs=["x"],
        created_at="2026-05-01T10:00:00+00:00",
    )


def test_write_then_read_claim_roundtrips(tmp_brain: Path):
    item_id = uuid.uuid4()
    claim = _make_claim(item_id)
    write_claim(tmp_brain, claim)

    loaded = read_claim(tmp_brain, claim.id)
    assert loaded == claim


def test_claim_body_contains_proposition_for_grep(tmp_brain: Path):
    item_id = uuid.uuid4()
    claim = _make_claim(item_id, prop="M3 stores claims as plain markdown.")
    path = write_claim(tmp_brain, claim)

    text = path.read_text()
    assert "M3 stores claims as plain markdown." in text
    # Frontmatter delimiter must surround a JSON block we can parse out.
    assert text.startswith("---\n")
    assert "\n---\n" in text


def test_iter_claims_yields_all_persisted(tmp_brain: Path):
    item_id = uuid.uuid4()
    a = _make_claim(item_id, prop="A.")
    b = _make_claim(item_id, prop="B.")
    write_claim(tmp_brain, a)
    write_claim(tmp_brain, b)

    seen = {c.id for c in iter_claims(tmp_brain)}
    assert seen == {a.id, b.id}


def test_claims_for_item_filters_by_source(tmp_brain: Path):
    item_a = uuid.uuid4()
    item_b = uuid.uuid4()
    write_claim(tmp_brain, _make_claim(item_a, prop="from a"))
    write_claim(tmp_brain, _make_claim(item_a, prop="also from a"))
    write_claim(tmp_brain, _make_claim(item_b, prop="from b"))

    a_claims = claims_for_item(tmp_brain, item_a)
    assert len(a_claims) == 2
    assert all(c.item_id == item_a for c in a_claims)


def test_delete_claims_for_item_removes_only_that_items(tmp_brain: Path):
    item_a = uuid.uuid4()
    item_b = uuid.uuid4()
    write_claim(tmp_brain, _make_claim(item_a))
    keep = _make_claim(item_b)
    write_claim(tmp_brain, keep)

    removed = delete_claims_for_item(tmp_brain, item_a)
    assert len(removed) == 1

    remaining = list(iter_claims(tmp_brain))
    assert {c.id for c in remaining} == {keep.id}


def test_read_claim_missing_returns_none(tmp_brain: Path):
    assert read_claim(tmp_brain, uuid.uuid4()) is None


def test_read_claim_with_corrupt_frontmatter_returns_none(tmp_brain: Path):
    p = tmp_brain / "claims"
    p.mkdir(parents=True, exist_ok=True)
    cid = uuid.uuid4()
    (p / f"{cid}.md").write_text("not even close to valid frontmatter\n")
    assert read_claim(tmp_brain, cid) is None
