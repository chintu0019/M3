"""Parse and maintain ~/brain/open_questions.md as a GitHub-flavored markdown checklist."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from m3.brain.layout import BrainPaths


@dataclass
class OpenQuestion:
    item_id: uuid.UUID
    question: str
    context_snippet: str


_LINE_RE = re.compile(r"^- \[(?P<state>[ x])\] (?P<rest>.+)$", re.MULTILINE)
_UNRESOLVED_SUFFIX = " (created {date}, item: {item_id})"
_RESOLVED_SUFFIX = " — answered {answer} on {date}"


def append(root: Path, q: OpenQuestion, *, created_date: str) -> None:
    p = BrainPaths(root)
    suffix = _UNRESOLVED_SUFFIX.format(date=created_date, item_id=q.item_id)
    ctx = f" — {q.context_snippet}" if q.context_snippet else ""
    line = f"- [ ] {q.question}{ctx}{suffix}\n"
    with p.open_questions.open("a") as fh:
        fh.write(line)


def list_unresolved(root: Path) -> list[str]:
    p = BrainPaths(root)
    text = p.open_questions.read_text()
    return [m.group("rest") for m in _LINE_RE.finditer(text) if m.group("state") == " "]


def resolve(root: Path, *, question_text: str, answer: str, resolved_date: str) -> bool:
    """Mark a question resolved in place. Matches by substring of question_text. Returns True if found."""
    p = BrainPaths(root)
    text = p.open_questions.read_text()
    updated: list[str] = []
    hit = False
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if m and m.group("state") == " " and question_text in m.group("rest"):
            suffix = _RESOLVED_SUFFIX.format(answer=answer, date=resolved_date)
            updated.append(f"- [x] {m.group('rest')}{suffix}")
            hit = True
        else:
            updated.append(line)
    p.open_questions.write_text("\n".join(updated) + ("\n" if text.endswith("\n") else ""))
    return hit
