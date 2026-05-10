import uuid as _u

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain
from m3.brain.items import ItemMeta, write_meta
from m3.brain.claims import ClaimMeta, write_claim


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def brain_and_app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    return brain, build_app(brain_root=brain, embedder=_Embedder())


def test_item_label_prefers_title(brain_and_app):
    brain, app = brain_and_app
    iid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None,
        extracted_text='---\ntitle: "Manoj Kesavulu"\n---\n\nbody here that should not be label',
        when_iso=None, when_source="ingest_time", hooks={},
        title="Manoj Kesavulu",
    ))
    c = TestClient(app)
    body = c.get("/api/v1/cluster/all").json()
    item_node = next((n for n in body["nodes"] if n["id"] == f"item:{iid}"), None)
    assert item_node is not None
    assert item_node["label"] == "Manoj Kesavulu"


def test_item_label_falls_back_when_no_title(brain_and_app):
    brain, app = brain_and_app
    iid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="raw fallback text",
        when_iso=None, when_source="ingest_time", hooks={},
        title=None,
    ))
    c = TestClient(app)
    body = c.get("/api/v1/cluster/all").json()
    item_node = next((n for n in body["nodes"] if n["id"] == f"item:{iid}"), None)
    assert item_node is not None
    assert "raw fallback text" in item_node["label"]


def test_claim_label_prefers_headline(brain_and_app):
    brain, app = brain_and_app
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="x",
        when_iso=None, when_source="ingest_time", hooks={},
    ))
    write_claim(brain, ClaimMeta(
        id=cid, item_id=iid,
        proposition="Manoj has been the CTO of three startups since 2018.",
        confidence=0.8, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        headline="Long CTO tenure",
    ))
    c = TestClient(app)
    body = c.get("/api/v1/cluster/all").json()
    claim_node = next((n for n in body["nodes"] if n["id"] == f"claim:{cid}"), None)
    assert claim_node is not None
    assert claim_node["label"] == "Long CTO tenure"


def test_claim_label_falls_back_to_proposition_when_no_headline(brain_and_app):
    brain, app = brain_and_app
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="x",
        when_iso=None, when_source="ingest_time", hooks={},
    ))
    write_claim(brain, ClaimMeta(
        id=cid, item_id=iid, proposition="Long full proposition with no headline yet.",
        confidence=0.5, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        # headline intentionally empty
    ))
    body = TestClient(app).get("/api/v1/cluster/all").json()
    claim_node = next(n for n in body["nodes"] if n["id"] == f"claim:{cid}")
    assert claim_node["label"].startswith("Long full proposition")


def test_cluster_node_includes_passthrough_fields(brain_and_app):
    """The full proposition / title / headline are also exposed so the frontend
    can render the expanded card without a second fetch."""
    brain, app = brain_and_app
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="x",
        when_iso=None, when_source="ingest_time", hooks={},
        title="The Title",
    ))
    write_claim(brain, ClaimMeta(
        id=cid, item_id=iid, proposition="Full proposition here.",
        confidence=0.8, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        headline="Headline",
    ))
    body = TestClient(app).get("/api/v1/cluster/all").json()
    item_node = next(n for n in body["nodes"] if n["id"] == f"item:{iid}")
    claim_node = next(n for n in body["nodes"] if n["id"] == f"claim:{cid}")
    assert item_node["title"] == "The Title"
    assert claim_node["headline"] == "Headline"
    assert claim_node["proposition"] == "Full proposition here."


def test_claim_headline_empty_string_serializes_as_null(brain_and_app):
    """The cluster builder converts ClaimMeta.headline=='' to None so the API
    surfaces JSON null. Keeps the wire shape consistent with the TS type
    (string | null), and lets the frontend's `node.headline ??` checks work."""
    brain, app = brain_and_app
    iid = _u.uuid4()
    cid = _u.uuid4()
    write_meta(brain, ItemMeta(
        id=iid, kind="personal", source="test", created_at="2026-01-01T00:00:00Z",
        original_filename=None, extracted_text="x",
        when_iso=None, when_source="ingest_time", hooks={},
    ))
    write_claim(brain, ClaimMeta(
        id=cid, item_id=iid,
        proposition="Headline-less claim.",
        confidence=0.5, supporting_span="...",
        entity_slugs=[], created_at="2026-01-01T00:00:00Z",
        # headline intentionally "" (the dataclass default)
    ))
    body = TestClient(app).get("/api/v1/cluster/all").json()
    claim_node = next(n for n in body["nodes"] if n["id"] == f"claim:{cid}")
    assert claim_node["headline"] is None     # not "", explicitly null
