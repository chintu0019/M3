from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.cli import app
from m3.core import config as _cfg


@pytest.fixture(autouse=True)
def _iso_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(_cfg.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    for k in ("M3_REQUIRE_AUTH", "M3_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_auth_generate_key_enables_and_prints_key():
    runner = CliRunner()
    r = runner.invoke(app, ["auth", "generate-key"])
    assert r.exit_code == 0, r.output
    key = r.output.strip()
    assert len(key) >= 32
    cfg = _cfg.load()
    assert cfg.auth.require_auth is True
    assert cfg.auth.api_key == key


def test_auth_show_key_reports_missing_when_no_key():
    runner = CliRunner()
    r = runner.invoke(app, ["auth", "show-key"])
    assert r.exit_code == 1
    assert "no key" in r.output.lower()


def test_auth_show_key_prints_after_generate():
    runner = CliRunner()
    g = runner.invoke(app, ["auth", "generate-key"])
    key = g.output.strip()
    r = runner.invoke(app, ["auth", "show-key"])
    assert r.exit_code == 0
    assert r.output.strip() == key


def test_auth_disable_turns_off_require_auth_but_keeps_key():
    runner = CliRunner()
    g = runner.invoke(app, ["auth", "generate-key"])
    key = g.output.strip()
    r = runner.invoke(app, ["auth", "disable"])
    assert r.exit_code == 0
    cfg = _cfg.load()
    assert cfg.auth.require_auth is False
    # Key preserved so re-enabling doesn't need a new one.
    assert cfg.auth.api_key == key
