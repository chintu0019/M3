from pathlib import Path

from m3.brain.hooks import HookHit, HookIndex


def test_upsert_and_search_by_who(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya", "Sarah"], what=["Pacific"], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="b", who=["Aditya"], what=[], where=["Bangalore"], project=["Pilot Path"], stance_entities=[])
    hits = idx.search("aditya", types=["who"], k=5)
    assert sorted(h.item_id for h in hits) == ["a", "b"]


def test_search_is_case_insensitive(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya"], what=[], where=[], project=[], stance_entities=[])
    hits = idx.search("ADITYA", types=["who"], k=5)
    assert [h.item_id for h in hits] == ["a"]


def test_search_by_multiple_types(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=[], what=["Pacific"], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="b", who=[], what=[], where=["Pacific Ocean"], project=[], stance_entities=[])
    hits = idx.search("pacific", types=["what", "where"], k=5)
    assert sorted(h.item_id for h in hits) == ["a", "b"]


def test_search_substring_match(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=[], what=["Pilot Path Group"], where=[], project=[], stance_entities=[])
    hits = idx.search("pilot", types=["what"], k=5)
    assert [h.item_id for h in hits] == ["a"]


def test_upsert_replaces_previous_hooks_for_item(tmp_brain: Path):
    idx = HookIndex.open(tmp_brain)
    idx.upsert_item_hooks(item_id="a", who=["Aditya"], what=[], where=[], project=[], stance_entities=[])
    idx.upsert_item_hooks(item_id="a", who=["Sarah"], what=[], where=[], project=[], stance_entities=[])
    hits_adi = idx.search("aditya", types=["who"], k=5)
    hits_sarah = idx.search("sarah", types=["who"], k=5)
    assert [h.item_id for h in hits_adi] == []
    assert [h.item_id for h in hits_sarah] == ["a"]
