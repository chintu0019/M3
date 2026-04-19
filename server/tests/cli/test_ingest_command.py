from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from m3.cli import app


def test_init_command_creates_brain(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "m3-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@m3.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "m3-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@m3.local")
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--brain", str(tmp_path / "brain")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "brain" / "self.md").is_file()


def test_ingest_command_with_fake_provider(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "m3-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@m3.local")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "m3-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@m3.local")
    monkeypatch.setenv("M3_LLM_PROVIDER", "fake")
    runner = CliRunner()
    brain = tmp_path / "brain"
    runner.invoke(app, ["init", "--brain", str(brain)])
    note = tmp_path / "note.txt"
    note.write_text("I dislike FluentCRM.")
    result = runner.invoke(app, ["ingest", str(note), "--brain", str(brain)])
    assert result.exit_code == 0, result.output
    # Meta file was written
    meta_dir = brain / "items" / "meta"
    assert any(meta_dir.iterdir()), "expected one meta file to be written"
