import uuid

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.items import ItemMeta, write_item, write_meta
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


def _seed(brain, item_id, *, ext="txt", content=b"hello world", filename="hello.txt",
          kind="personal", text="hello world", created_at="2026-04-19T10:00:00+00:00",
          hooks=None, llm_output_raw=None, archived=False):
    if content is not None:
        write_item(brain, item_id, extension=ext, content=content)
    write_meta(brain, ItemMeta(
        id=item_id, kind=kind, source="cli",
        created_at=created_at, original_filename=filename,
        extracted_text=text, when_iso="2026-04-19", when_source="ingest_time",
        hooks=hooks or {}, llm_output_raw=llm_output_raw or {}, confidence=0.8,
        archived=archived,
    ))


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    item_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    _seed(brain, item_id)
    return build_app(brain_root=brain, embedder=_Embedder())


def test_get_item_meta(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert body["extracted_text"] == "hello world"
    assert body["archived"] is False


def test_get_item_original_bytes(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/original")
    assert r.status_code == 200
    assert r.content == b"hello world"


def test_item_missing_returns_404(app):
    client = TestClient(app)
    r = client.get("/api/v1/items/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert r.status_code == 404


# --- list endpoint ---


@pytest.fixture
def populated(tmp_path):
    """Brain with three items of different content kinds and timestamps."""
    brain = tmp_path / "brain"
    init_brain(brain)
    _seed(
        brain, uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ext="pdf", content=b"%PDF-1.4 stub", filename="report.pdf",
        text="quarterly revenue report", created_at="2026-04-01T00:00:00+00:00",
        hooks={"who": [{"name": "Acme"}], "what": [{"name": "revenue"}]},
    )
    _seed(
        brain, uuid.UUID("22222222-2222-2222-2222-222222222222"),
        ext="png", content=b"\x89PNG\r\n", filename="chart.png",
        text="bar chart of sales", created_at="2026-04-15T00:00:00+00:00",
    )
    _seed(
        brain, uuid.UUID("33333333-3333-3333-3333-333333333333"),
        ext=None, content=None, filename=None,
        text="just a text-only ingest", created_at="2026-04-20T00:00:00+00:00",
    )
    return brain


def test_list_items_default_returns_all_unarchived_newest_first(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    ids = [e["id"] for e in body["items"]]
    assert ids[0].startswith("33333333")
    assert ids[-1].startswith("11111111")
    pdf_row = next(e for e in body["items"] if e["id"].startswith("11111111"))
    assert pdf_row["content_kind"] == "pdf"
    assert pdf_row["entity_count"] == 2
    assert pdf_row["has_original"] is True


def test_list_items_filters_by_content_kind(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items?content_kind=pdf")
    body = r.json()
    assert [e["id"][:8] for e in body["items"]] == ["11111111"]
    r = client.get("/api/v1/items?content_kind=image&content_kind=text")
    body = r.json()
    got = sorted(e["id"][:8] for e in body["items"])
    assert got == ["22222222", "33333333"]


def test_list_items_substring_search(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items?q=chart")
    assert [e["id"][:8] for e in r.json()["items"]] == ["22222222"]


def test_list_items_pagination_with_cursor(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items?limit=2")
    page1 = r.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    r = client.get(f"/api/v1/items?limit=2&cursor={page1['next_cursor']}")
    page2 = r.json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None
    seen = {e["id"] for e in page1["items"]} | {e["id"] for e in page2["items"]}
    assert len(seen) == 3


def test_list_items_excludes_archived_by_default(populated):
    item_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
    _seed(populated, item_id, ext="txt", content=b"x", filename="archived.txt",
          text="hidden item", archived=True,
          created_at="2026-04-25T00:00:00+00:00")
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items")
    assert all(not e["archived"] for e in r.json()["items"])
    r = client.get("/api/v1/items?include_archived=true")
    assert any(e["archived"] for e in r.json()["items"])


# --- text + provenance ---


def test_get_item_text_returns_truncation_flag(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items/11111111-1111-1111-1111-111111111111/text")
    assert r.status_code == 200
    assert r.json() == {"extracted_text": "quarterly revenue report", "truncated": False}
    r = client.get("/api/v1/items/11111111-1111-1111-1111-111111111111/text?max_chars=10")
    body = r.json()
    assert body["truncated"] is True
    assert len(body["extracted_text"]) == 10


def test_provenance_returns_entities_and_facts(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    item_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
    _seed(
        brain, item_id, ext="txt", content=b"x", filename="prov.txt",
        text="met Aditya about M3", hooks={"who": [{"name": "Aditya"}]},
        llm_output_raw={
            "entity_updates": [{
                "canonical_name": "Aditya",
                "entity_type": "person",
                "section_update": {"change_summary": "noted weekly meeting", "new_content": "Weekly", "section_heading": "## Cadence", "operation": "append"},
            }],
            "self_updates": [{"slot": "People", "change_summary": "weekly with Aditya"}],
            "open_questions": [{"question": "When is the next sync?"}],
        },
    )
    app = build_app(brain_root=brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get(f"/api/v1/items/{item_id}/provenance")
    assert r.status_code == 200
    body = r.json()
    assert body["entities_touched"] == [
        {"slug": "aditya", "canonical_name": "Aditya", "entity_type": "person", "role": "updated"},
    ]
    fact_sources = {f["source"] for f in body["facts"]}
    assert {"self_updates", "entity_updates", "hooks"} <= fact_sources
    assert body["questions"] == ["When is the next sync?"]


# --- archive ---


def test_archive_round_trip_hides_from_list_and_recovers(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    target = "11111111-1111-1111-1111-111111111111"
    r = client.post(f"/api/v1/items/{target}/archive", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["archived"] is True
    listed = client.get("/api/v1/items").json()
    assert target not in {e["id"] for e in listed["items"]}
    r = client.post(f"/api/v1/items/{target}/archive", json={"archived": False})
    assert r.json()["archived"] is False
    listed = client.get("/api/v1/items").json()
    assert target in {e["id"] for e in listed["items"]}


def test_thumbnail_404_when_missing(populated):
    app = build_app(brain_root=populated, embedder=_Embedder())
    client = TestClient(app)
    r = client.get("/api/v1/items/11111111-1111-1111-1111-111111111111/thumbnail")
    assert r.status_code == 404


def test_thumbnail_generated_for_image(tmp_path):
    """Image uploads should produce a thumbnail JPEG that the API serves."""
    from io import BytesIO

    from PIL import Image

    from m3.brain.thumbnails import generate_thumbnail
    brain = tmp_path / "brain"
    init_brain(brain)
    item_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
    src = brain / "items" / "originals" / f"{item_id}.png"
    img = Image.new("RGB", (640, 480), (200, 100, 50))
    img.save(src, "PNG")
    write_meta(brain, ItemMeta(
        id=item_id, kind="reference", source="cli",
        created_at="2026-04-19T10:00:00+00:00", original_filename="pic.png",
        extracted_text="", when_iso=None, when_source="ingest_time",
        hooks={}, llm_output_raw={}, confidence=0.0,
    ))
    out = generate_thumbnail(brain, item_id, original_path=src, content_kind="image")
    assert out is not None and out.exists()
    app = build_app(brain_root=brain, embedder=_Embedder())
    client = TestClient(app)
    r = client.get(f"/api/v1/items/{item_id}/thumbnail")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
