"""Append-only changelog: one line per file patch."""

from __future__ import annotations

from pathlib import Path

from m3.brain.layout import BrainPaths


def append(root: Path, *, timestamp: str, target: str, summary: str) -> None:
    p = BrainPaths(root)
    line = f"- {timestamp} | {target} | {summary}\n"
    with p.changelog.open("a") as fh:
        fh.write(line)
