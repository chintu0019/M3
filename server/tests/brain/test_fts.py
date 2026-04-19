from pathlib import Path

from m3.brain.fts import FTSHit, FTSIndex


def test_upsert_and_search(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="Had a call with Aditya about Pilot Path.")
    idx.upsert_item(item_id="b", text="FluentCRM is the wrong tool for us.")
    idx.upsert_item(item_id="c", text="Uber receipt for 42 dollars.")
    hits = idx.search("Aditya", k=5)
    assert [h.id for h in hits] == ["a"]
    hits = idx.search("wrong tool", k=5)
    assert [h.id for h in hits] == ["b"]
    idx.close()


def test_upsert_is_idempotent(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="first")
    idx.upsert_item(item_id="a", text="second")
    hits = idx.search("second", k=5)
    assert [h.id for h in hits] == ["a"]
    hits = idx.search("first", k=5)
    assert hits == []
    idx.close()


def test_rank_order_uses_bm25(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="match_strong", text="apple apple apple banana")
    idx.upsert_item(item_id="match_weak", text="apple is a fruit")
    hits = idx.search("apple", k=2)
    # match_strong should rank first because "apple" appears more often
    assert hits[0].id == "match_strong"
    idx.close()


def test_search_returns_score_and_snippet(tmp_brain: Path):
    idx = FTSIndex.open(tmp_brain)
    idx.upsert_item(item_id="a", text="Meeting with Aditya on Thursday about the Pacific project.")
    hits = idx.search("Pacific", k=1)
    assert len(hits) == 1
    assert isinstance(hits[0], FTSHit)
    assert hits[0].score > 0.0
    assert "Pacific" in hits[0].snippet
    idx.close()
