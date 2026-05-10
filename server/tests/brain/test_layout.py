import subprocess
from pathlib import Path

import pytest

from m3.brain.layout import BrainPaths, init_brain, is_initialized


def test_init_brain_creates_directory_structure(tmp_path: Path):
    init_brain(tmp_path)
    assert (tmp_path / "self.md").is_file()
    assert (tmp_path / "entities").is_dir()
    assert (tmp_path / "items" / "originals").is_dir()
    assert (tmp_path / "items" / "meta").is_dir()
    assert (tmp_path / "records").is_dir()
    assert (tmp_path / "signals").is_dir()
    assert (tmp_path / "open_questions.md").is_file()
    assert (tmp_path / "changelog.md").is_file()
    assert (tmp_path / "index").is_dir()
    assert (tmp_path / ".git").is_dir()


def test_init_brain_is_idempotent(tmp_path: Path):
    init_brain(tmp_path)
    (tmp_path / "self.md").write_text("# do not clobber\n")
    init_brain(tmp_path)
    assert (tmp_path / "self.md").read_text() == "# do not clobber\n"


def test_self_md_has_fixed_slots_on_fresh_init(tmp_path: Path):
    init_brain(tmp_path)
    body = (tmp_path / "self.md").read_text()
    for slot in ("## Preferences", "## People", "## Projects", "## Goals", "## Context", "## Beliefs", "## Timeline"):
        assert slot in body, f"missing slot {slot!r} in fresh self.md"


def test_is_initialized_detects_uninitialized_dir(tmp_path: Path):
    assert is_initialized(tmp_path) is False


def test_is_initialized_detects_initialized_dir(tmp_path: Path):
    init_brain(tmp_path)
    assert is_initialized(tmp_path) is True


def test_init_brain_creates_baseline_commit(tmp_path: Path):
    """Fresh init must leave a HEAD commit so post-ingest rollbacks have a target."""
    init_brain(tmp_path)
    # `git rev-parse HEAD` returns non-zero (128) on an unborn branch, and 0 once
    # a commit exists. Before the fix this failed with 128.
    subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True,
    )


def test_brain_paths_resolves_all_locations(tmp_path: Path):
    init_brain(tmp_path)
    p = BrainPaths(tmp_path)
    assert p.self_md == tmp_path / "self.md"
    assert p.entities_dir == tmp_path / "entities"
    assert p.items_originals == tmp_path / "items" / "originals"
    assert p.items_meta == tmp_path / "items" / "meta"
    assert p.records_dir == tmp_path / "records"
    assert p.signals_dir == tmp_path / "signals"
    assert p.open_questions == tmp_path / "open_questions.md"
    assert p.changelog == tmp_path / "changelog.md"
    assert p.vectors_db == tmp_path / "index" / "vectors.sqlite"
    assert p.entity_path("pilot-path") == tmp_path / "entities" / "pilot-path.md"


def test_brainpaths_exposes_topical_db(tmp_brain: Path):
    from m3.brain.layout import BrainPaths
    p = BrainPaths(tmp_brain)
    assert p.topical_db == tmp_brain / "index" / "topical.sqlite"
