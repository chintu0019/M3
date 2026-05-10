from pathlib import Path

import pytest

from m3.brain.topical import TopicalIndex, TOPICAL_DIM


def test_topical_index_upsert_and_get(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    vec = [0.1] * TOPICAL_DIM
    idx.upsert("entity:manoj", vec)
    got = idx.get("entity:manoj")
    assert got is not None
    assert len(got) == TOPICAL_DIM
    assert pytest.approx(got[0], abs=1e-6) == 0.1


def test_topical_index_get_missing_returns_none(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    assert idx.get("entity:nonexistent") is None


def test_topical_index_upsert_overwrites(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    idx.upsert("claim:abc", [0.1] * TOPICAL_DIM)
    idx.upsert("claim:abc", [0.5] * TOPICAL_DIM)
    got = idx.get("claim:abc")
    assert got is not None
    assert pytest.approx(got[0], abs=1e-6) == 0.5


def test_topical_index_iter_all(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    idx.upsert("entity:a", [0.1] * TOPICAL_DIM)
    idx.upsert("claim:b", [0.2] * TOPICAL_DIM)
    rows = list(idx.iter_all())
    ids = {r[0] for r in rows}
    assert ids == {"entity:a", "claim:b"}


def test_topical_dim_validates(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    with pytest.raises(ValueError):
        idx.upsert("entity:a", [0.1] * (TOPICAL_DIM - 1))


def test_topical_index_delete_removes_row(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    idx.upsert("claim:abc", [0.1] * TOPICAL_DIM)
    assert idx.get("claim:abc") is not None
    idx.delete("claim:abc")
    assert idx.get("claim:abc") is None


def test_topical_index_delete_missing_is_noop(tmp_brain: Path):
    idx = TopicalIndex.open(tmp_brain)
    idx.delete("claim:nonexistent")  # should not raise
    assert idx.get("claim:nonexistent") is None
