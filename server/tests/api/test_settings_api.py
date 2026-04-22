from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from m3.app import build_app
from m3.brain.layout import init_brain


class _Embedder:
    dim = 768

    async def embed(self, texts):
        return [[0.0] * 768 for _ in texts]


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("M3_CONFIG_DIR", str(tmp_path / "cfg"))
    # Scrub any env vars that would show up as "overrides".
    for k in ("M3_LLM_PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL",
              "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def app(tmp_path):
    brain = tmp_path / "brain"
    init_brain(brain)
    return build_app(brain_root=brain, embedder=_Embedder())


def test_get_settings_returns_defaults(app):
    c = TestClient(app)
    r = c.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "ollama"
    assert body["ollama_model"] == "qwen2.5:7b"
    assert body["anthropic_api_key_present"] is False
    assert body["env_overrides"] == []


def test_put_settings_switches_provider(app):
    c = TestClient(app)
    r = c.put("/api/v1/settings", json={"provider": "anthropic"})
    assert r.status_code == 200
    assert r.json()["provider"] == "anthropic"
    # Subsequent GET reflects persisted change
    assert c.get("/api/v1/settings").json()["provider"] == "anthropic"


def test_put_settings_stores_api_key_and_redacts_on_read(app):
    c = TestClient(app)
    r = c.put("/api/v1/settings", json={"anthropic_api_key": "sk-ant-secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["anthropic_api_key_present"] is True
    # Key itself is NOT in the response payload
    assert "sk-ant-secret" not in r.text


def test_put_settings_clears_api_key(app):
    c = TestClient(app)
    c.put("/api/v1/settings", json={"anthropic_api_key": "sk-ant-secret"})
    r = c.put("/api/v1/settings", json={"clear_anthropic_api_key": True})
    assert r.json()["anthropic_api_key_present"] is False


def test_env_override_surfaces_in_response(app, monkeypatch):
    monkeypatch.setenv("M3_LLM_PROVIDER", "anthropic")
    c = TestClient(app)
    body = c.get("/api/v1/settings").json()
    assert body["provider"] == "anthropic"
    assert "M3_LLM_PROVIDER" in body["env_overrides"]


def test_put_rejects_unknown_provider(app):
    c = TestClient(app)
    r = c.put("/api/v1/settings", json={"provider": "gpt5"})
    assert r.status_code == 422
