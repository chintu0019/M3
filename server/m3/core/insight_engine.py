"""
M3 Insight Engine — after every entity-mode ingest, look for patterns in
the 2-hop neighbourhood of the touched entities and persist typed
insights.

Capable-provider work: `engine.find_insights` is the expensive part.
This module handles the neighbourhood walk, recent-facts loading, name
-> id resolution, dedup, and persistence.

Dedup key: `(insight_type, sorted(related_entity_ids))`. We skip rows
that already exist with status in (`new`, `acknowledged`) so the user
doesn't see the same observation twice on every re-ingest. Dismissed
insights can re-fire — intentional, since dismissed then re-observed
is a signal the user cares about.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.core.engines.base import CompilationEngine
from m3.storage.models import (
    Entity,
    EntityFact,
    EntityFactLink,
    EntityLink,
    Insight as InsightRow,
)

logger = logging.getLogger("m3.insight_engine")

# How many recent facts we hand the LLM for context. Newest-first, per
# entity in the neighbourhood. Scales with neighbourhood size but capped
# in the engine prompt itself.
RECENT_FACTS_PER_ENTITY = 20


async def _neighbourhood(
    session: AsyncSession, seed_ids: Iterable[uuid.UUID], depth: int = 2,
) -> list[Entity]:
    """Return entities within `depth` hops of any seed via entity_links.
    Seeds themselves are excluded from the result (the caller already has
    them)."""
    frontier = set(seed_ids)
    visited = set(frontier)
    for _ in range(depth):
        if not frontier:
            break
        stmt = select(EntityLink.source_entity_id, EntityLink.target_entity_id).where(
            EntityLink.source_entity_id.in_(frontier)
            | EntityLink.target_entity_id.in_(frontier)
        )
        rows = (await session.execute(stmt)).all()
        next_frontier: set[uuid.UUID] = set()
        for src, tgt in rows:
            for eid in (src, tgt):
                if eid not in visited:
                    next_frontier.add(eid)
                    visited.add(eid)
        frontier = next_frontier

    reach = visited - set(seed_ids)
    if not reach:
        return []
    stmt = select(Entity).where(Entity.id.in_(reach))
    return list((await session.execute(stmt)).scalars().all())


async def _recent_facts(
    session: AsyncSession, entity_ids: Iterable[uuid.UUID], per_entity: int,
) -> list[dict]:
    """Load recent facts for these entities, flattened and newest-first."""
    ids = list(entity_ids)
    if not ids:
        return []
    # One query over the lot, then partition per-entity in Python so we
    # can cap per-entity independently. The link table gives us the role.
    stmt = (
        select(
            EntityFact.id, EntityFact.content, EntityFact.fact_type,
            EntityFact.item_id, EntityFact.created_at,
            Entity.canonical_name, Entity.id.label("entity_id"),
            EntityFactLink.role,
        )
        .join(EntityFactLink, EntityFactLink.fact_id == EntityFact.id)
        .join(Entity, Entity.id == EntityFactLink.entity_id)
        .where(EntityFactLink.entity_id.in_(ids))
        .order_by(EntityFact.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()

    per_entity_count: dict[uuid.UUID, int] = {}
    out: list[dict] = []
    for r in rows:
        eid = r.entity_id
        if per_entity_count.get(eid, 0) >= per_entity:
            continue
        per_entity_count[eid] = per_entity_count.get(eid, 0) + 1
        out.append({
            "item_id": str(r.item_id),
            "content": r.content,
            "fact_type": r.fact_type,
            "entity_name": r.canonical_name,
            "entity_id": str(r.entity_id),
            "role": r.role,
            "created_at": r.created_at,
        })
    return out


def _entity_row_to_dict(e: Entity) -> dict:
    return {
        "id": str(e.id),
        "canonical_name": e.canonical_name,
        "entity_type": e.entity_type,
        "description": e.description,
    }


async def _resolve_names_to_ids(
    session: AsyncSession, names: list[str], hint_ids: set[uuid.UUID],
) -> list[uuid.UUID]:
    """Map the LLM's free-text entity names back to real entity ids,
    preferring entities already in the neighbourhood/touched set."""
    if not names:
        return []
    lowered = {n.lower() for n in names if n}
    stmt = select(Entity).where(func.lower(Entity.canonical_name).in_(lowered))
    rows = (await session.execute(stmt)).scalars().all()

    # Group by name: prefer the entity already in hint_ids, else first.
    by_name: dict[str, uuid.UUID] = {}
    for e in rows:
        key = e.canonical_name.lower()
        if key not in by_name or e.id in hint_ids:
            by_name[key] = e.id
    return list(dict.fromkeys(by_name[n] for n in lowered if n in by_name))


async def _dedup_exists(
    session: AsyncSession, insight_type: str, entity_ids: list[uuid.UUID],
) -> bool:
    """True if a new/acknowledged insight already covers this shape."""
    if not entity_ids:
        # Insights with no entity refs dedup on type only — rare, but
        # we don't want a flood.
        stmt = select(func.count(InsightRow.id)).where(
            InsightRow.insight_type == insight_type,
            InsightRow.status.in_(["new", "acknowledged"]),
            func.cardinality(InsightRow.related_entity_ids) == 0,
        )
        count = (await session.execute(stmt)).scalar_one()
        return count > 0

    sorted_ids = sorted(entity_ids, key=str)
    stmt = select(InsightRow).where(
        InsightRow.insight_type == insight_type,
        InsightRow.status.in_(["new", "acknowledged"]),
    )
    for row in (await session.execute(stmt)).scalars().all():
        if sorted(row.related_entity_ids, key=str) == sorted_ids:
            return True
    return False


async def find_for_touched(
    session: AsyncSession,
    engine: CompilationEngine,
    touched_entity_ids: list[uuid.UUID],
) -> int:
    """Run one insight pass scoped to the given set of just-touched entities.
    Returns the number of new insight rows written. Callers are expected to
    swallow any exception — this method logs and returns 0 on error."""
    if not touched_entity_ids:
        return 0

    # 1) Load touched entity rows + neighbourhood.
    touched_rows = (
        await session.execute(select(Entity).where(Entity.id.in_(touched_entity_ids)))
    ).scalars().all()
    if not touched_rows:
        return 0

    touched_ids = {e.id for e in touched_rows}
    nbhd_rows = await _neighbourhood(session, touched_ids, depth=2)
    all_ids = touched_ids | {e.id for e in nbhd_rows}

    # 2) Load recent facts over the neighbourhood.
    recent_facts = await _recent_facts(session, all_ids, RECENT_FACTS_PER_ENTITY)

    # 3) Ask the engine.
    try:
        proposals = await engine.find_insights(
            touched_entities=[_entity_row_to_dict(e) for e in touched_rows],
            neighborhood=[_entity_row_to_dict(e) for e in nbhd_rows],
            recent_facts=recent_facts,
        )
    except NotImplementedError:
        return 0
    except Exception as e:
        logger.warning(f"find_insights raised: {e}")
        return 0

    if not proposals:
        return 0

    # 4) Resolve names/ids, dedup, insert.
    written = 0
    for prop in proposals:
        entity_ids = await _resolve_names_to_ids(
            session, prop.related_entity_names, hint_ids=all_ids,
        )
        item_ids: list[uuid.UUID] = []
        for raw in prop.related_item_ids:
            try:
                item_ids.append(uuid.UUID(raw))
            except (ValueError, TypeError):
                continue

        if await _dedup_exists(session, prop.type, entity_ids):
            continue

        session.add(InsightRow(
            insight_type=prop.type,
            title=prop.title,
            description=prop.description,
            related_entity_ids=entity_ids,
            related_item_ids=item_ids,
            status="new",
        ))
        written += 1

    if written:
        await session.flush()
    return written
