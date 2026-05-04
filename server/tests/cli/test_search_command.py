import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3.cli import app


def _git_env(monkeypatch):
    for key, val in {
        "GIT_AUTHOR_NAME": "m3-test", "GIT_AUTHOR_EMAIL": "test@m3.local",
        "GIT_COMMITTER_NAME": "m3-test", "GIT_COMMITTER_EMAIL": "test@m3.local",
        "M3_LLM_PROVIDER": "fake",
    }.items():
        monkeypatch.setenv(key, val)


def test_search_command_returns_ranked_results(tmp_path: Path, monkeypatch):
    _git_env(monkeypatch)
    runner = CliRunner()
    brain = tmp_path / "brain"
    runner.invoke(app, ["init", "--brain", str(brain)])
    note = tmp_path / "note.txt"
    note.write_text("Had coffee with Aditya about Pacific.")
    runner.invoke(app, ["ingest", str(note), "--brain", str(brain)])
    result = runner.invoke(app, ["search", "coffee", "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    assert "coffee" in result.output.lower() or "aditya" in result.output.lower()


def test_reindex_command_runs(tmp_path: Path, monkeypatch):
    _git_env(monkeypatch)
    runner = CliRunner()
    brain = tmp_path / "brain"
    runner.invoke(app, ["init", "--brain", str(brain)])
    result = runner.invoke(app, ["reindex", "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    assert "indexed" in result.output.lower()
