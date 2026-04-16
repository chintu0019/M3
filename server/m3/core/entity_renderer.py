"""
M3 Entity Renderer — regenerate wiki-style pages for entities that
accumulated new facts since their last render.

Picks dirty entities in priority order (most new facts first), loads
their facts + related entities, calls `engine.render_entity`, validates
that every [^<item_id>] citation in the output resolves to a real fact
on that entity, and persists. A per-entity commit boundary means a
failure on entity N doesn't undo entities 1..N-1.

Citation validation is intentionally strict: if any citation is invalid,
the whole page falls back to a deterministic markdown template. This
keeps the entity page useful even when the model misbehaves, and lets
us tune prompts from the warning logs over time without silent drift.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.core.engines.base import CompilationEngine, RenderedPage
from m3.core.llm import EmbeddingProvider, LLMProvider
from m3.storage.files import FileStore
from m3.storage.models import Entity, EntityFact, EntityFactLink, EntityLink

logger = logging.getLogger("m3.entity_renderer")

# [^<uuid>] — the uuid grammar is permissive on hyphen placement so the
# regex keeps working if the LLM omits the standard 8-4-4-4-12 dashes.
_CITATION_RE = re.compile(r"\[\^([0-9a-fA-F-]{30,36})\]")


def _extract_citations(text: str) -> set[str]:
    """Normalise every [^...] citation to a lowercase stripped string."""
    return {m.group(1).strip().lower() for m in _CITATION_RE.finditer(text or "")}


async def _load_entity_facts(session, entity_id: uuid.UUID) -> list[dict]:
    """Return all facts attached to this entity, newest first, with the
    role this entity plays in each fact."""
    stmt = (
        select(EntityFact, EntityFactLink.role)
        .join(EntityFactLink, EntityFactLink.fact_id == EntityFact.id)
        .where(EntityFactLink.entity_id == entity_id)
        .order_by(EntityFact.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "item_id": str(fact.item_id),
            "content": fact.content,
            "fact_type": fact.fact_type,
            "source_quote": fact.source_quote,
            "confidence": fact.confidence,
            "created_at": fact.created_at,
            "fact_time": fact.fact_time,
            "role": role,
        }
        for fact, role in rows
    ]


async def _load_related(session, entity_id: uuid.UUID, limit: int = 10) -> list[dict]:
    """Top related entities (by link weight) in either direction."""
    out_stmt = (
        select(Entity.canonical_name, Entity.entity_type, EntityLink.link_type, EntityLink.weight)
        .join(EntityLink, EntityLink.target_entity_id == Entity.id)
        .where(EntityLink.source_entity_id == entity_id)
    )
    in_stmt = (
        select(Entity.canonical_name, Entity.entity_type, EntityLink.link_type, EntityLink.weight)
        .join(EntityLink, EntityLink.source_entity_id == Entity.id)
        .where(EntityLink.target_entity_id == entity_id)
    )
    rows = list((await session.execute(out_stmt)).all()) + list((await session.execute(in_stmt)).all())
    # Dedupe by (name, link_type) keeping max weight
    dedup: dict[tuple[str, str], tuple[str, str, str, int]] = {}
    for name, etype, link_type, weight in rows:
        key = (name, link_type)
        prev = dedup.get(key)
        if prev is None or (prev[3] or 0) < (weight or 0):
            dedup[key] = (name, etype, link_type, weight or 0)
    ranked = sorted(dedup.values(), key=lambda r: r[3], reverse=True)[:limit]
    return [
        {"name": n, "type": t, "link_type": lt, "weight": w}
        for n, t, lt, w in ranked
    ]


def _deterministic_fallback(
    entity: Entity, facts: list[dict], related: list[dict],
) -> RenderedPage:
    """Used when the engine's output fails citation validation. Every fact
    is a cited bullet; no synthesis is attempted. Always valid by
    construction."""
    lines = [f"# {entity.canonical_name}"]
    lines.append("")
    lines.append(f"**Type:** {entity.entity_type}  ")
    if entity.aliases:
        lines.append(f"**Aliases:** {', '.join(entity.aliases)}  ")
    if entity.description:
        lines.append("")
        lines.append(entity.description)

    if facts:
        lines.append("")
        lines.append("## Facts")
        lines.append("")
        for f in facts:
            lines.append(f"- {f['content']} [^{f['item_id']}]")

    if related:
        lines.append("")
        lines.append("## Related")
        lines.append("")
        for r in related:
            lines.append(f"- {r['name']} ({r['type']}) — {r['link_type']}")

    overview = ""
    if facts:
        top = facts[0]
        overview = f"{top['content']} [^{top['item_id']}]"

    return RenderedPage(content="\n".join(lines).strip(), overview=overview)


async def render_dirty_entities(
    db: async_sessionmaker,
    files: FileStore,
    engine: CompilationEngine,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    limit: int = 20,
) -> int:
    """Render up to `limit` dirty entities. Returns count rendered."""
    async with db() as session:
        pick_stmt = (
            select(Entity.id)
            .where(Entity.page_dirty.is_(True))
            .order_by(Entity.facts_since_render.desc(), Entity.updated_at.asc())
            .limit(limit)
        )
        ids = [row[0] for row in (await session.execute(pick_stmt)).all()]

    if not ids:
        return 0

    rendered = 0
    for ent_id in ids:
        try:
            async with db() as session:
                ent = await session.get(Entity, ent_id)
                if ent is None:
                    continue
                facts = await _load_entity_facts(session, ent_id)
                if not facts:
                    # No facts to render — clear the dirty flag so we don't
                    # loop on an empty entity.
                    ent.page_dirty = False
                    ent.facts_since_render = 0
                    await session.commit()
                    continue
                related = await _load_related(session, ent_id)

                entity_dict = {
                    "canonical_name": ent.canonical_name,
                    "entity_type": ent.entity_type,
                    "aliases": list(ent.aliases or []),
                    "description": ent.description,
                }
                try:
                    page = await engine.render_entity(entity_dict, facts, related)
                except NotImplementedError:
                    logger.warning("Engine does not support render_entity; skipping")
                    return rendered
                except Exception as e:
                    logger.exception(f"render_entity raised for {ent.canonical_name}: {e}")
                    page = _deterministic_fallback(ent, facts, related)

                valid_ids = {str(f["item_id"]).lower() for f in facts}
                cited = _extract_citations(page.content) | _extract_citations(page.overview)
                bad = cited - valid_ids
                if bad:
                    logger.warning(
                        f"Invalid citations on {ent.canonical_name} "
                        f"({len(bad)} bogus item_ids): {sorted(bad)[:3]}... "
                        f"falling back to deterministic template"
                    )
                    page = _deterministic_fallback(ent, facts, related)

                ent.page_content = page.content
                ent.page_overview = page.overview
                ent.page_dirty = False
                ent.facts_since_render = 0
                ent.updated_at = datetime.now(timezone.utc)
                await session.commit()
                rendered += 1
        except Exception:
            logger.exception(f"Failed to render entity {ent_id}")
            # Continue with the next entity.

    logger.info(f"Rendered {rendered}/{len(ids)} dirty entities")
    return rendered
