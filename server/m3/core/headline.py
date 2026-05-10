"""Stand-alone headline generator for backfill paths.

Fresh ingests get headlines as part of the main ClaimOut LLM call.
This module handles the case where existing claims (extracted before
the headline field existed) need a headline filled in retroactively
without re-running the full extract."""

from __future__ import annotations

from typing import Protocol


_HEADLINE_PROMPT = """Generate a 3-7 word interpretive tag-style label for this claim.

The label captures the concept the claim is about, NOT a paraphrase of
the sentence. Strong verbs, concrete nouns. Avoid the subject's name
(it appears elsewhere on the canvas).

Examples:
  Claim: "Manoj has been the CTO of three early-stage startups since 2018."
  Headline: Long CTO tenure

  Claim: "Project PACIFIC Phase 1 has a target completion of June 14, 2026."
  Headline: Phase 1 deadline: Jun 14

  Claim: "GDPR exposure on publicly addressable endpoints was flagged in the legal review."
  Headline: GDPR risk flagged

Now do this one. Reply with only the headline, nothing else.

Claim: {proposition}
Headline:"""


class _LLM(Protocol):
    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...


async def generate_headline(*, proposition: str, llm: _LLM) -> str:
    """Ask the LLM for an interpretive headline. Cleans + caps at 80 chars."""
    raw = await llm.complete(
        messages=[{"role": "user", "content": _HEADLINE_PROMPT.format(proposition=proposition.strip())}],
        max_tokens=80,
        temperature=0.2,
    )
    if not raw:
        return ""
    # Take only the first line — many models append commentary after a newline.
    headline = raw.splitlines()[0].strip()
    # Strip surrounding quotes / trailing periods.
    headline = headline.strip("\"'").rstrip(".").strip()
    return headline[:80]
