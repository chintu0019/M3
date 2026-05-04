"""Read/write ~/brain/self.md by fixed slot, with append | replace_section | revise operations.

Fixed slots live as ## H2 headings. Subsections inside a slot are ### H3 headings
the LLM names. All three operations return the prior content (empty string if none).
"""

from __future__ import annotations

import re
from pathlib import Path

from m3.brain.layout import SELF_SLOTS, BrainPaths


class SelfDocError(Exception):
    pass


_EMPTY_PLACEHOLDER = "_(empty)_"


def _split_by_slot(text: str) -> dict[str, str]:
    """Return {slot_name: body_text_without_the_heading_line}."""
    out: dict[str, str] = {}
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip("\n")
    return out


def _reassemble(header: str, slots: dict[str, str]) -> str:
    parts = [header.rstrip()]
    for slot in SELF_SLOTS:
        body = slots.get(slot, _EMPTY_PLACEHOLDER) or _EMPTY_PLACEHOLDER
        parts.append(f"\n\n## {slot}\n\n{body.strip()}\n")
    return "".join(parts).rstrip() + "\n"


def _read_all(root: Path) -> tuple[str, dict[str, str]]:
    p = BrainPaths(root)
    raw = p.self_md.read_text()
    first_h2 = raw.find("\n## ")
    header = raw[:first_h2] if first_h2 != -1 else raw.split("\n", 1)[0] + "\n"
    slots = _split_by_slot(raw)
    return header, slots


def read_section(root: Path, slot: str) -> str:
    if slot not in SELF_SLOTS:
        raise SelfDocError(f"unknown self slot: {slot!r}")
    _, slots = _read_all(root)
    return slots.get(slot, _EMPTY_PLACEHOLDER)


def apply_update(
    root: Path, *, slot: str, operation: str, new_content: str, heading: str | None,
) -> str:
    """Apply an operation to a slot. Returns the prior slot body (before the change)."""
    if slot not in SELF_SLOTS:
        raise SelfDocError(f"unknown self slot: {slot!r}")
    if operation not in {"append", "replace_section", "revise"}:
        raise SelfDocError(f"unknown operation: {operation!r}")
    p = BrainPaths(root)
    header, slots = _read_all(root)
    prior = slots.get(slot, _EMPTY_PLACEHOLDER)
    current = "" if prior == _EMPTY_PLACEHOLDER else prior

    # LLMs occasionally emit heading equal to the slot name (e.g. slot="Preferences",
    # heading="Preferences" or "## Preferences"), meaning "replace the whole slot body".
    # Normalize to that intent by falling back to an append (on empty) or full-body
    # replace (on non-empty) rather than searching for a subsection that cannot exist.
    if heading is not None:
        normalized_heading = heading.strip().lstrip("#").strip().lower()
        if normalized_heading == slot.lower():
            heading = None
            if operation in {"replace_section", "revise"}:
                slots[slot] = new_content.strip()
                p.self_md.write_text(_reassemble(header, slots))
                return prior

    if operation == "append":
        slots[slot] = (current + "\n\n" + new_content.strip()).strip() if current else new_content.strip()
    elif operation in {"replace_section", "revise"}:
        if not heading:
            raise SelfDocError(f"{operation} requires a heading")
        if heading not in current:
            # Graceful fallback: heading not found, append the new content
            # instead of crashing the whole ingest.
            slots[slot] = (current + "\n\n" + new_content.strip()).strip() if current else new_content.strip()
        else:
            slots[slot] = _replace_subsection(current, heading, new_content.strip())

    p.self_md.write_text(_reassemble(header, slots))
    return prior


def _replace_subsection(body: str, heading: str, replacement: str) -> str:
    """Replace the block that starts with `heading` (an H3/H4 line) up to the next sibling heading or EOF."""
    sibling = re.compile(r"^#{3,4} .+$", re.MULTILINE)
    matches = list(sibling.finditer(body))
    for i, m in enumerate(matches):
        line = body[m.start():m.end()]
        if line.strip() == heading.strip():
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            return (body[:start] + replacement.rstrip() + "\n\n" + body[end:]).strip()
    raise SelfDocError(f"heading {heading!r} not matched as a subsection")
