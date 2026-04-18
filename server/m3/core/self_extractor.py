"""
M3 Self Extractor — conversation-aware pass for the compiler.

Given a conversation transcript, ask the LLM what the user revealed
about themselves, and write/update entities of entity_type='self'.

Returns the list of touched entity ids so the caller can changelog
them and the canvas can refresh.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.core.llm import LLMProvider
from m3.storage.models import Entity

logger = logging.getLogger("m3.self_extractor")

SYSTEM_PROMPT = """You are extracting self-knowledge from a conversation between the user and an assistant.

You will receive:
- The current self-knowledge entries (what's already known about the user).
- A conversation transcript.

Your job: identify what the conversation revealed about the user that should be added to or refined in the self-knowledge.

Rules:
- Only include facts the USER themselves revealed, not assistant guesses.
- Be specific. "Likes Python" is weak; "Prefers Python over Go for scripting because of typing ergonomics" is useful.
- Update existing entries when the new info refines them; create new entries only when the topic genuinely doesn't fit.
- If nothing was revealed, return an empty updates list.

Respond with strict JSON only — no prose, no fencing:

{
  "updates": [
    {
      "canonical_name": "preferences" | "context" | "goals" | "people" | "<new lowercase slug>",
      "page_content": "<full new markdown for this entity — replace, don't append>",
      "rationale": "<one short sentence on why this update>"
    }
  ]
}
"""


def _format_existing(entries: list[Entity]) -> str:
    if not entries:
        return "(none yet)"
    parts = []
    for e in entries:
        parts.append(f"## {e.canonical_name}\n{(e.page_content or '').strip() or '(empty)'}")
    return "\n\n".join(parts)


async def extract_self_facts(
    db_factory: async_sessionmaker,
    llm: LLMProvider,
    transcript: str,
) -> list[uuid.UUID]:
    """Run the conversation through the self-extraction prompt and persist updates.
    Returns the list of touched entity ids."""

    async with db_factory() as session:
        existing = (
            await session.execute(
                select(Entity).where(Entity.entity_type == "self")
            )
        ).scalars().all()

    user_message = (
        f"## Existing self-knowledge\n\n{_format_existing(list(existing))}\n\n"
        f"## Conversation\n\n{transcript}"
    )

    raw = await llm.complete(
        messages=[{"role": "user", "content": user_message}],
        system=SYSTEM_PROMPT,
        temperature=0.2,
    )
    raw = raw.strip()
    # Be forgiving about ```json fences just in case the model adds them.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Self extractor returned non-JSON; skipping. Raw: %s", raw[:200])
        return []

    updates = parsed.get("updates") or []
    if not isinstance(updates, list):
        return []

    touched: list[uuid.UUID] = []
    async with db_factory() as session:
        for u in updates:
            if not isinstance(u, dict):
                continue
            name = (u.get("canonical_name") or "").strip().lower()
            page = u.get("page_content")
            if not name or not isinstance(page, str):
                continue
            ent = (
                await session.execute(
                    select(Entity).where(
                        Entity.entity_type == "self",
                        Entity.canonical_name == name,
                    )
                )
            ).scalar_one_or_none()
            if ent is None:
                ent = Entity(
                    canonical_name=name,
                    entity_type="self",
                    description=u.get("rationale"),
                    page_content=page,
                    page_dirty=False,
                    page_overview=(page[:240] if page else None),
                )
                session.add(ent)
                await session.flush()
            else:
                ent.page_content = page
                ent.page_overview = page[:240] if page else None
                ent.page_dirty = False
                ent.updated_at = datetime.now(timezone.utc)
            touched.append(ent.id)
        await session.commit()
    return touched
