import os
import stat
from pathlib import Path

import pytest

from m3.core import config as cfg


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(cfg.CONFIG_DIR_ENV, str(tmp_path / "m3cfg"))
    # Clear env vars that would otherwise override in these tests.
    for key in (
        "M3_TELEGRAM_TOKEN", "M3_TELEGRAM_ALLOWED_CHATS", "M3_SERVER_URL",
        "M3_LLM_PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL",
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def test_load_returns_blank_when_missing():
    c = cfg.load()
    assert c.telegram.token is None
    assert c.telegram.allowed_chats == []
    assert c.telegram.server_url is None


def test_save_and_load_roundtrip():
    c = cfg.M3Config()
    c.telegram.token = "abc:xyz"
    c.telegram.allowed_chats = [1, 2, 3]
    c.telegram.server_url = "http://host:7007"
    path = cfg.save(c)
    assert path.exists()
    loaded = cfg.load()
    assert loaded.telegram.token == "abc:xyz"
    assert loaded.telegram.allowed_chats == [1, 2, 3]
    assert loaded.telegram.server_url == "http://host:7007"


def test_save_sets_mode_600():
    c = cfg.M3Config()
    c.telegram.token = "abc"
    path = cfg.save(c)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"expected 600, got {oct(mode)}"


def test_malformed_yaml_is_treated_as_blank(tmp_path):
    cfg.config_dir().mkdir(parents=True, exist_ok=True)
    cfg.config_path().write_text(":\n  bad: [yaml")
    c = cfg.load()
    assert c.telegram.token is None


def test_env_token_overrides_config(monkeypatch):
    cfg.save(cfg.M3Config(telegram=cfg.TelegramConfig(token="from-file")))
    monkeypatch.setenv("M3_TELEGRAM_TOKEN", "from-env")
    assert cfg.telegram_token() == "from-env"


def test_env_allowed_chats_overrides_config(monkeypatch):
    c = cfg.M3Config()
    c.telegram.allowed_chats = [111]
    cfg.save(c)
    monkeypatch.setenv("M3_TELEGRAM_ALLOWED_CHATS", "222,333")
    assert cfg.telegram_allowed_chats() == frozenset({222, 333})


def test_allowed_chats_falls_back_to_config():
    c = cfg.M3Config()
    c.telegram.allowed_chats = [444]
    cfg.save(c)
    assert cfg.telegram_allowed_chats() == frozenset({444})


def test_server_url_precedence(monkeypatch):
    c = cfg.M3Config()
    c.telegram.server_url = "http://file:1"
    cfg.save(c)
    assert cfg.telegram_server_url() == "http://file:1"
    monkeypatch.setenv("M3_SERVER_URL", "http://env:2")
    assert cfg.telegram_server_url() == "http://env:2"


def test_update_helper_mutates_and_saves():
    def _set(c: cfg.M3Config) -> cfg.M3Config:
        c.telegram.token = "via-update"
        c.telegram.allowed_chats = [7, 8]
        return c
    cfg.update(_set)
    reloaded = cfg.load()
    assert reloaded.telegram.token == "via-update"
    assert reloaded.telegram.allowed_chats == [7, 8]


def test_load_coerces_allowed_chats_to_int():
    cfg.config_dir().mkdir(parents=True, exist_ok=True)
    cfg.config_path().write_text("telegram:\n  allowed_chats:\n    - '42'\n    - not-a-number\n    - 7\n")
    c = cfg.load()
    # '42' coerces; 'not-a-number' dropped; 7 passes through
    assert c.telegram.allowed_chats == [42, 7]


def test_llm_config_roundtrip():
    c = cfg.M3Config()
    c.llm.provider = "anthropic"
    c.llm.anthropic_api_key = "sk-test"
    c.llm.anthropic_model = "claude-opus-4"
    cfg.save(c)
    loaded = cfg.load()
    assert loaded.llm.provider == "anthropic"
    assert loaded.llm.anthropic_api_key == "sk-test"
    assert loaded.llm.anthropic_model == "claude-opus-4"


def test_llm_config_env_overrides(monkeypatch):
    cfg.save(cfg.M3Config(llm=cfg.LLMConfig(provider="ollama", ollama_model="llama3")))
    assert cfg.llm_provider() == "ollama"
    assert cfg.ollama_model() == "llama3"
    monkeypatch.setenv("M3_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:72b")
    assert cfg.llm_provider() == "anthropic"
    assert cfg.ollama_model() == "qwen2.5:72b"


def test_canvas_v2_defaults_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("M3_CONFIG_DIR", str(tmp_path))
    loaded = cfg.load()
    assert loaded.canvas.v2 is False


def test_canvas_v2_round_trips_through_save_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("M3_CONFIG_DIR", str(tmp_path))
    initial = cfg.load()
    initial.canvas.v2 = True
    cfg.save(initial)
    reloaded = cfg.load()
    assert reloaded.canvas.v2 is True


def test_canvas_v2_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("M3_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("M3_CANVAS_V2", "true")
    assert cfg.canvas_v2_enabled() is True
    monkeypatch.setenv("M3_CANVAS_V2", "0")
    assert cfg.canvas_v2_enabled() is False
