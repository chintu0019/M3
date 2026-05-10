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


def test_item_meta_title_round_trips(tmp_brain: Path):
    import uuid as _u
    from m3.brain.items import ItemMeta, write_meta, read_meta
    iid = _u.uuid4()
    meta = ItemMeta(
        id=iid, kind="personal", source="test",
        created_at="2026-01-01T00:00:00Z",
        original_filename="notes.md",
        extracted_text="some body",
        when_iso=None, when_source="ingest_time", hooks={},
        title="Manoj's notes",
    )
    write_meta(tmp_brain, meta)
    loaded = read_meta(tmp_brain, iid)
    assert loaded is not None
    assert loaded.title == "Manoj's notes"


def test_item_meta_title_defaults_none_for_legacy_files(tmp_brain: Path):
    """Existing item meta JSONs without `title` should still load."""
    import uuid as _u
    import json
    from m3.brain.items import read_meta
    from m3.brain.layout import BrainPaths
    p = BrainPaths(tmp_brain)
    p.items_meta.mkdir(parents=True, exist_ok=True)
    iid = _u.uuid4()
    legacy = {
        "id": str(iid),
        "kind": "personal", "source": "x",
        "created_at": "2026-01-01T00:00:00Z",
        "original_filename": None,
        "extracted_text": "old item",
        "when_iso": None,
        "when_source": "unknown",
        "hooks": {},
        # NOTE: no `title` field
    }
    (p.items_meta / f"{iid}.json").write_text(json.dumps(legacy))
    loaded = read_meta(tmp_brain, iid)
    assert loaded is not None
    assert loaded.title is None
