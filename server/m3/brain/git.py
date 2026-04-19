"""Stage + commit changes under ~/brain/ after each ingest."""

from __future__ import annotations

import subprocess
from pathlib import Path


def has_changes(root: Path) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def commit_ingest(root: Path, *, item_id: str, summary: str) -> None:
    if not has_changes(root):
        return
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"ingest {item_id}: {summary}"],
        cwd=root, check=True,
    )
