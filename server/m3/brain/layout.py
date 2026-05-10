"""Filesystem layout for ~/brain/. Owns directory creation, path resolution, and the fresh self.md skeleton."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

SELF_SLOTS: tuple[str, ...] = (
    "Preferences", "People", "Projects", "Goals", "Context", "Beliefs", "Timeline",
)

_FRESH_SELF_MD = (
    "# Self\n\n"
    + "\n\n".join(f"## {slot}\n\n_(empty)_" for slot in SELF_SLOTS)
    + "\n"
)

_FRESH_OPEN_QUESTIONS = "# Open questions\n\n"
_FRESH_CHANGELOG = "# Changelog\n\n"


@dataclass(frozen=True)
class BrainPaths:
    root: Path

    @property
    def self_md(self) -> Path: return self.root / "self.md"
    @property
    def entities_dir(self) -> Path: return self.root / "entities"
    @property
    def items_originals(self) -> Path: return self.root / "items" / "originals"
    @property
    def items_meta(self) -> Path: return self.root / "items" / "meta"
    @property
    def claims_dir(self) -> Path: return self.root / "claims"
    @property
    def syntheses_dir(self) -> Path: return self.root / "syntheses"
    @property
    def records_dir(self) -> Path: return self.root / "records"
    @property
    def signals_dir(self) -> Path: return self.root / "signals"
    @property
    def open_questions(self) -> Path: return self.root / "open_questions.md"
    @property
    def changelog(self) -> Path: return self.root / "changelog.md"
    @property
    def index_dir(self) -> Path: return self.root / "index"
    @property
    def vectors_db(self) -> Path: return self.index_dir / "vectors.sqlite"
    @property
    def topical_db(self) -> Path: return self.index_dir / "topical.sqlite"
    @property
    def config_yml(self) -> Path: return self.root / "config.yml"

    def entity_path(self, slug: str) -> Path:
        return self.entities_dir / f"{slug}.md"


def is_initialized(root: Path) -> bool:
    return (root / "self.md").is_file() and (root / ".git").is_dir()


def init_brain(root: Path) -> BrainPaths:
    """Create the ~/brain/ skeleton. Idempotent: existing files are preserved."""
    root.mkdir(parents=True, exist_ok=True)
    p = BrainPaths(root)
    for d in (p.entities_dir, p.items_originals, p.items_meta, p.claims_dir, p.syntheses_dir, p.records_dir, p.signals_dir, p.index_dir):
        d.mkdir(parents=True, exist_ok=True)
        # Empty directories aren't tracked by git, which means `git clean -fd` on
        # rollback would delete them. A .gitkeep keeps the skeleton intact across
        # resets even if ingests leave no files behind.
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.write_text("")
    if not p.self_md.exists():
        p.self_md.write_text(_FRESH_SELF_MD)
    if not p.open_questions.exists():
        p.open_questions.write_text(_FRESH_OPEN_QUESTIONS)
    if not p.changelog.exists():
        p.changelog.write_text(_FRESH_CHANGELOG)
    freshly_inited_git = False
    if not (root / ".git").is_dir():
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        freshly_inited_git = True
    if freshly_inited_git:
        # Every brain needs a baseline commit so that post-ingest `git reset --hard HEAD`
        # has a real target to reset to on rollback. Skip if the repo already had history.
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "initial brain skeleton"],
            cwd=root, check=True,
        )
    return p
