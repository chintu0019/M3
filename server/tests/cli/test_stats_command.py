from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.cli import app


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("M3_LOG_DIR", str(tmp_path / "state"))


def _write(rows: list[dict], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    p = log_dir / "llm-calls.jsonl"
    with p.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def test_stats_no_file(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["stats"])
    assert r.exit_code == 0
    assert "no llm-calls.jsonl yet" in r.output


def test_stats_summary(tmp_path):
    now = datetime.now(timezone.utc)
    _write([
        {"ts": now.isoformat(), "provider": "anthropic",
         "model": "claude-sonnet-4", "method": "complete_tool",
         "prompt_chars": 100, "input_tokens": 50, "output_tokens": 75,
         "latency_ms": 1000, "status": "ok"},
        {"ts": now.isoformat(), "provider": "anthropic",
         "model": "claude-sonnet-4", "method": "complete_tool",
         "prompt_chars": 200, "input_tokens": 30, "output_tokens": 40,
         "latency_ms": 500, "status": "ok"},
    ], tmp_path / "state")
    runner = CliRunner()
    r = runner.invoke(app, ["stats"])
    assert r.exit_code == 0, r.output
    assert "anthropic" in r.output
    assert "calls=   2" in r.output
    assert "in=    80" in r.output    # 50 + 30
    assert "out=   115" in r.output   # 75 + 40
    assert "avg=750ms" in r.output    # (1000+500)/2


def test_stats_window_excludes_old_entries(tmp_path):
    now = datetime.now(timezone.utc)
    _write([
        {"ts": (now - timedelta(days=30)).isoformat(), "provider": "ollama",
         "model": "qwen2.5:7b", "method": "complete", "latency_ms": 500},
        {"ts": now.isoformat(), "provider": "ollama",
         "model": "qwen2.5:7b", "method": "complete", "latency_ms": 1500},
    ], tmp_path / "state")
    runner = CliRunner()
    r = runner.invoke(app, ["stats", "--days", "7"])
    assert r.exit_code == 0
    assert "calls=   1" in r.output
    assert "avg=1500ms" in r.output


def test_stats_counts_errors(tmp_path):
    now = datetime.now(timezone.utc)
    _write([
        {"ts": now.isoformat(), "provider": "anthropic",
         "model": "claude-sonnet-4", "method": "complete_tool",
         "status": "ok", "latency_ms": 100},
        {"ts": now.isoformat(), "provider": "anthropic",
         "model": "claude-sonnet-4", "method": "complete_tool",
         "status": "error:APIError", "latency_ms": 50},
    ], tmp_path / "state")
    runner = CliRunner()
    r = runner.invoke(app, ["stats"])
    assert r.exit_code == 0
    assert "errors=  1" in r.output


def test_stats_ignores_malformed_lines(tmp_path):
    now = datetime.now(timezone.utc)
    log_dir = tmp_path / "state"
    log_dir.mkdir(parents=True)
    p = log_dir / "llm-calls.jsonl"
    p.write_text(
        "not json\n"
        + json.dumps({"ts": now.isoformat(), "provider": "ollama",
                      "model": "qwen", "method": "complete",
                      "latency_ms": 200}) + "\n"
        + "\n"  # blank line
    )
    runner = CliRunner()
    r = runner.invoke(app, ["stats"])
    assert r.exit_code == 0
    assert "calls=   1" in r.output
