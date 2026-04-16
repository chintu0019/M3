"""
M3 Type Consolidator — runs the engine's consolidate_types pass and
rewrites base-table rows onto the canonical survivor.

The entity_types / fact_types / fact_roles dim tables accrue every type
the LLM has ever emitted. Organic vocabulary is great for flexibility
but it drifts: 'person' and 'individual', 'project' and 'projects',
'attributed_to' and 'attributed-to'. A daily pass asks the LLM which
names mean the same thing, then rewrites the base rows so queries don't
have to dereference merged_into on read.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.core.engines.base import CompilationEngine
from m3.storage.models import (
    EntityTypeVocab,
    FactRoleVocab,
    FactTypeVocab,
)

logger = logging.getLogger("m3.type_consolidator")


# (vocab model, base table, column to rewrite, summary key in result dict)
_VOCAB_TABLES = [
    (EntityTypeVocab, "entities", "entity_type", "entity_types"),
    (FactTypeVocab, "entity_facts", "fact_type", "fact_types"),
    (FactRoleVocab, "entity_fact_links", "role", "fact_roles"),
]


async def _load_active(session, model) -> list[dict]:
    """Load vocab rows that aren't already merged into something else."""
    stmt = select(model).where(model.merged_into.is_(None)).order_by(model.usage_count.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {"name": r.name, "usage_count": r.usage_count or 0, "parent_type": r.parent_type}
        for r in rows
    ]


async def consolidate_types(
    db: async_sessionmaker,
    engine: CompilationEngine,
) -> dict[str, int]:
    """Run one consolidation pass. Returns a count summary per vocabulary."""
    async with db() as session:
        entity_types = await _load_active(session, EntityTypeVocab)
        fact_types = await _load_active(session, FactTypeVocab)
        fact_roles = await _load_active(session, FactRoleVocab)

    try:
        merges = await engine.consolidate_types(entity_types, fact_types, fact_roles)
    except NotImplementedError:
        logger.info("Engine does not implement consolidate_types; skipping")
        return {k: 0 for _, _, _, k in _VOCAB_TABLES}

    summary: dict[str, int] = {k: 0 for _, _, _, k in _VOCAB_TABLES}

    async with db() as session:
        for model, base_table, column, key in _VOCAB_TABLES:
            applied = 0
            for merge in merges.get(key) or []:
                frm, to = merge["from"], merge["to"]
                from_row = await session.get(model, frm)
                to_row = await session.get(model, to)
                if from_row is None:
                    logger.warning(f"Skip merge {key}: {frm!r} does not exist")
                    continue
                if from_row.merged_into is not None:
                    continue  # already merged on a previous pass
                if to_row is None:
                    # Survivor doesn't exist yet — create a row so usage
                    # counts stay consistent.
                    to_row = model(name=to, usage_count=0)
                    session.add(to_row)
                    await session.flush()

                # Rewrite base table rows onto the canonical name. Parameterised
                # statements keep this safe against odd type names.
                await session.execute(
                    text(f"UPDATE {base_table} SET {column} = :to WHERE {column} = :frm"),
                    {"to": to, "frm": frm},
                )

                to_row.usage_count = (to_row.usage_count or 0) + (from_row.usage_count or 0)
                from_row.usage_count = 0
                from_row.merged_into = to
                applied += 1
                logger.info(
                    f"Consolidated {key}: {frm!r} -> {to!r} ({merge.get('reason','')})"
                )
            summary[key] = applied
        await session.commit()

    return summary
