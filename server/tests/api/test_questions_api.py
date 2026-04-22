import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain
from m3.brain.questions import OpenQuestion, append


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    append(brain, OpenQuestion(
        item_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        question="Who is J?", context_snippet="call w/ J at 3pm",
    ), created_date="2026-04-19")
    return build_app(brain_root=brain, embedder=_Embedder())


def test_list_open_questions(app):
    client = TestClient(app)
    r = client.get("/api/v1/open-questions")
    assert r.status_code == 200
    body = r.json()
    assert len(body["questions"]) == 1
    assert "Who is J?" in body["questions"][0]["question"]


def test_resolve_question(app):
    client = TestClient(app)
    r = client.post("/api/v1/open-questions/resolve",
                    json={"question_text": "Who is J?", "answer": "Jerome"})
    assert r.status_code == 200
    assert r.json()["resolved"] is True
    r2 = client.get("/api/v1/open-questions")
    assert r2.json()["questions"] == []


def test_resolve_missing_question_returns_false(app):
    client = TestClient(app)
    r = client.post("/api/v1/open-questions/resolve",
                    json={"question_text": "does not exist", "answer": "x"})
    assert r.status_code == 200
    assert r.json()["resolved"] is False
