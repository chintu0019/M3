from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain
from m3.core import config as _cfg


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture(autouse=True)
def _iso_config(tmp_path, monkeypatch):
    """Isolate config dir per-test and clear the auth env vars.

    Tests that want auth on set the env vars themselves.
    """
    monkeypatch.setenv(_cfg.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    for k in ("M3_REQUIRE_AUTH", "M3_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    return build_app(brain_root=brain, embedder=_Embedder())


def test_auth_off_by_default(app):
    c = TestClient(app)
    r = c.get("/api/v1/status")
    assert r.status_code == 200


def test_auth_blocks_when_required_and_no_header(app, monkeypatch):
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    monkeypatch.setenv("M3_API_KEY", "test-key")
    c = TestClient(app)
    r = c.get("/api/v1/status")
    assert r.status_code == 401


def test_auth_accepts_valid_bearer(app, monkeypatch):
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    monkeypatch.setenv("M3_API_KEY", "test-key")
    c = TestClient(app)
    r = c.get("/api/v1/status", headers={"Authorization": "Bearer test-key"})
    assert r.status_code == 200


def test_auth_rejects_wrong_bearer(app, monkeypatch):
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    monkeypatch.setenv("M3_API_KEY", "real-key")
    c = TestClient(app)
    r = c.get("/api/v1/status", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401


def test_auth_rejects_non_bearer_header(app, monkeypatch):
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    monkeypatch.setenv("M3_API_KEY", "real-key")
    c = TestClient(app)
    r = c.get("/api/v1/status", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code == 401


def test_auth_does_not_gate_spa_routes(app, monkeypatch):
    """Static/SPA routes must stay reachable even with auth on; only /api/ is gated."""
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    monkeypatch.setenv("M3_API_KEY", "test-key")
    c = TestClient(app)
    # No client/dist is mounted in this test, so the route returns 404 — the
    # point is that auth does NOT convert it to 401.
    r = c.get("/some-route")
    assert r.status_code != 401


def test_auth_required_but_no_key_configured_returns_500(app, monkeypatch):
    monkeypatch.setenv("M3_REQUIRE_AUTH", "1")
    # Deliberately no M3_API_KEY.
    c = TestClient(app)
    r = c.get("/api/v1/status")
    assert r.status_code == 500
    assert "generate-key" in r.json()["detail"]


def test_generate_key_produces_fresh_token():
    from m3.api.auth import generate_key

    a = generate_key()
    b = generate_key()
    assert a != b
    assert len(a) >= 32
