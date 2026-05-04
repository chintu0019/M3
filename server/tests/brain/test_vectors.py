from pathlib import Path

from m3.brain.vectors import VectorIndex


def test_upsert_item_embedding_is_retrievable(tmp_brain: Path):
    idx = VectorIndex.open(tmp_brain)
    idx.upsert_item(item_id="abc", embedding=[0.1] * 768)
    idx.upsert_item(item_id="def", embedding=[0.2] * 768)
    hits = idx.nearest_items(query=[0.11] * 768, k=2)
    assert [h.id for h in hits] == ["abc", "def"]
    idx.close()


def test_upsert_same_id_twice_updates_in_place(tmp_brain: Path):
    idx = VectorIndex.open(tmp_brain)
    idx.upsert_item(item_id="abc", embedding=[0.0] * 768)
    idx.upsert_item(item_id="abc", embedding=[1.0] * 768)
    assert idx.count_items() == 1
    idx.close()


def test_upsert_entity_embedding_is_retrievable(tmp_brain: Path):
    idx = VectorIndex.open(tmp_brain)
    idx.upsert_entity(slug="pilot-path", embedding=[0.5] * 768)
    hits = idx.nearest_entities(query=[0.5] * 768, k=1)
    assert [h.id for h in hits] == ["pilot-path"]
    idx.close()
