"""Pure title-extraction for items. Tries YAML frontmatter, Markdown H1,
first non-empty line, filename stem, in that order. Returns None if there
is no signal at all. No LLM call; deterministic and cheap."""

from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TITLE_LINE_RE = re.compile(r'^title\s*:\s*(?:"([^"]+)"|\'([^\']+)\'|(.+?))\s*$', re.MULTILINE)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_MAX = 120


def extract_title(extracted_text: str | None, original_filename: str | None) -> str | None:
    text = (extracted_text or "").strip()
    if text:
        # YAML frontmatter title
        m = _FRONTMATTER_RE.match(text)
        if m:
            block = m.group(1)
            tm = _TITLE_LINE_RE.search(block)
            if tm:
                value = (tm.group(1) or tm.group(2) or tm.group(3) or "").strip()
                if value:
                    return value[:_MAX]
            # Frontmatter without title — strip it and continue with the body.
            text = text[m.end():].strip()

        # Markdown H1
        hm = _H1_RE.search(text)
        if hm:
            return hm.group(1).strip()[:_MAX]

        # First non-empty line
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line[:_MAX]

    # Filename fallback
    if original_filename:
        stem = Path(original_filename).stem
        cleaned = stem.replace("-", " ").replace("_", " ").strip()
        if cleaned:
            return cleaned[:_MAX]

    return None
