import json
import uuid
from pathlib import Path

from m3.brain.items import ItemMeta, read_meta, write_item, write_meta


def test_write_item_stores_original_bytes(tmp_brain: Path):
    item_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    write_item(tmp_brain, item_id, extension="txt", content=b"hello world")
    assert (tmp_brain / "items" / "originals" / f"{item_id}.txt").read_bytes() == b"hello world"


def test_write_meta_roundtrip(tmp_brain: Path):
    item_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    meta = ItemMeta(
        id=item_id,
        kind="personal",
        source="telegram",
        created_at="2026-04-19T10:00:00+00:00",
        original_filename="note.txt",
        extracted_text="hello",
        when_iso="2026-04-19",
        when_source="ingest_time",
        hooks={"who": [], "what": [], "where": [], "project": [], "stance": []},
        llm_output_raw={"kind": "personal"},
        confidence=0.9,
    )
    write_meta(tmp_brain, meta)
    loaded = read_meta(tmp_brain, item_id)
    assert loaded == meta


def test_read_meta_missing_returns_none(tmp_brain: Path):
    assert read_meta(tmp_brain, uuid.uuid4()) is None


def test_write_meta_writes_pretty_json(tmp_brain: Path):
    item_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    meta = ItemMeta(
        id=item_id, kind="personal", source="cli", created_at="2026-04-19T10:00:00+00:00",
        original_filename=None, extracted_text="x", when_iso=None, when_source="unknown",
        hooks={}, llm_output_raw={}, confidence=0.0,
    )
    write_meta(tmp_brain, meta)
    raw = (tmp_brain / "items" / "meta" / f"{item_id}.json").read_text()
    parsed = json.loads(raw)
    assert parsed["id"] == str(item_id)
    assert "\n  " in raw, "expected pretty-printed JSON with 2-space indent"
