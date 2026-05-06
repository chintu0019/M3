"""Best-effort auto-naming for chat sessions.

After the first assistant turn lands on a fresh session, ask the configured
LLM for a 3-6 word title and persist it. Locked titles (user renames) are
skipped. Failures are swallowed: the user always sees *some* title via the
derived-first-user-message fallback in read_meta.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from m3.brain import chats as _chats

logger = logging.getLogger(__name__)

_PROMPT = (
    "You are titling a chat conversation for a sidebar list. "
    "Read the user's first message and the assistant's first reply, then "
    "produce a concise 3-6 word title that captures the topic. "
    "Output ONLY the title text - no quotes, no punctuation at the end, "
    "no leading 'Title:'."
)


class _MinimalLLM(Protocol):
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...


def _clean(raw: str) -> str:
    s = (raw or "").strip()
    # Strip wrapping quotes and any trailing punctuation that adds no value.
    if len(s) >= 2 and s[0] in {'"', "'"} and s[-1] == s[0]:
        s = s[1:-1].strip()
    while s and s[-1] in {".", "!", "?"}:
        s = s[:-1].rstrip()
    return s[:60]


async def generate_and_save_title(root: Path, sid: str, llm: _MinimalLLM) -> None:
    """Generate a title for the given session and persist it via write_meta.

    Pre-conditions:
      - Session has at least one user turn AND one assistant turn.
      - Existing meta has title_locked == False.

    Always returns. Never raises. On any failure or pre-condition miss the
    function is a no-op and the derived title remains.
    """
    try:
        meta = _chats.read_meta(root, sid)
        if meta.get("title_locked"):
            return

        turns = _chats.load_session(root, sid)
        first_user = next((t for t in turns if t["role"] == "user"), None)
        first_asst = next((t for t in turns if t["role"] == "assistant"), None)
        if not first_user or not first_asst:
            return

        prompt = (
            f"User: {first_user['content'][:1000]}\n\n"
            f"Assistant: {first_asst['content'][:1500]}"
        )
        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_PROMPT,
            max_tokens=60,
            temperature=0.3,
        )
        title = _clean(raw)
        if not title:
            return

        # title_locked=False so future runs of this routine could still
        # update - though in practice we only fire this once per session.
        _chats.write_meta(root, sid, title=title, title_locked=False)
    except Exception as e:
        logger.warning("auto_title failed for session %s: %s", sid, e)
