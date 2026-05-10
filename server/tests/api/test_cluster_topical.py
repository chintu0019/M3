from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.entity_doc import EntityDoc, upsert as upsert_entity
from m3.brain.layout import init_brain
from m3.brain.topical import TopicalIndex, TOPICAL_DIM


class _Embedder:
    dim = 768
    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def brain_and_app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    # Seed two entities so the cluster has nodes to render.
    upsert_entity(brain, EntityDoc(canonical_name="Manoj", entity_type="person", body="CTO."))
    upsert_entity(brain, EntityDoc(canonical_name="PACIFIC", entity_type="project", body="Launch."))
    app = build_app(brain_root=brain, embedder=_Embedder())
    return brain, app


def test_cluster_all_includes_topical_vec_when_present(brain_and_app):
    brain, app = brain_and_app
    # Pre-populate one entity vector in the topical index.
    idx = TopicalIndex.open(brain)
    idx.upsert("entity:manoj", [0.1] * TOPICAL_DIM)
    idx.close()

    c = TestClient(app)
    r = c.get("/api/v1/cluster/all")
    assert r.status_code == 200
    body = r.json()
    manoj_nodes = [n for n in body["nodes"] if n["id"] == "entity:manoj"]
    assert manoj_nodes, "entity:manoj not found in cluster/all response"
    manoj = manoj_nodes[0]
    assert manoj.get("topical_vec") is not None
    assert len(manoj["topical_vec"]) == TOPICAL_DIM
    assert pytest.approx(manoj["topical_vec"][0], abs=1e-6) == 0.1


def test_cluster_all_omits_topical_vec_for_unindexed_nodes(brain_and_app):
    brain, app = brain_and_app
    idx = TopicalIndex.open(brain)
    idx.upsert("entity:manoj", [0.1] * TOPICAL_DIM)
    idx.close()

    c = TestClient(app)
    r = c.get("/api/v1/cluster/all")
    body = r.json()
    # Every node that does NOT have an index entry should report topical_vec=None.
    for n in body["nodes"]:
        if n["id"] != "entity:manoj":
            assert n.get("topical_vec") in (None, []), (
                f"node {n['id']} unexpectedly has topical_vec={n.get('topical_vec')}"
            )


def test_cluster_query_includes_topical_vec(brain_and_app):
    """build_cluster (the query-driven one) should also populate topical_vec."""
    brain, app = brain_and_app
    idx = TopicalIndex.open(brain)
    idx.upsert("entity:manoj", [0.2] * TOPICAL_DIM)
    idx.close()

    c = TestClient(app)
    r = c.get("/api/v1/cluster", params={"q": "Manoj"})
    assert r.status_code == 200
    body = r.json()
    manoj_nodes = [n for n in body["nodes"] if n["id"] == "entity:manoj"]
    if manoj_nodes:
        assert manoj_nodes[0].get("topical_vec") is not None
        assert len(manoj_nodes[0]["topical_vec"]) == TOPICAL_DIM
