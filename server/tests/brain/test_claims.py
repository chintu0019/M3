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


def test_claim_meta_headline_round_trips(tmp_brain: Path):
    import uuid as _u
    from m3.brain.claims import ClaimMeta, write_claim, read_claim
    cid = _u.uuid4()
    meta = ClaimMeta(
        id=cid, item_id=_u.uuid4(),
        proposition="Manoj has been the CTO of three startups.",
        confidence=0.8, supporting_span="...",
        headline="Long CTO tenure",
    )
    write_claim(tmp_brain, meta)
    loaded = read_claim(tmp_brain, cid)
    assert loaded is not None
    assert loaded.headline == "Long CTO tenure"


def test_claim_meta_headline_defaults_empty_for_legacy_files(tmp_brain: Path):
    """Existing claim files written before this field should still load."""
    import uuid as _u
    import json
    from m3.brain.claims import read_claim
    from m3.brain.layout import BrainPaths
    p = BrainPaths(tmp_brain)
    p.claims_dir.mkdir(parents=True, exist_ok=True)
    cid = _u.uuid4()
    legacy_frontmatter = {
        "id": str(cid),
        "item_id": str(_u.uuid4()),
        "proposition": "legacy claim",
        "confidence": 0.5,
        "supporting_span": "...",
        "entity_slugs": [],
        "created_at": "",
        # NOTE: no `headline` field
    }
    (p.claims_dir / f"{cid}.md").write_text(
        "---\n" + json.dumps(legacy_frontmatter, indent=2) + "\n---\n\nlegacy claim\n"
    )
    loaded = read_claim(tmp_brain, cid)
    assert loaded is not None
    assert loaded.headline == ""
