"""
M3 Entity Resolver — map an EntityMention from the extractor to an Entity row.

Layered strategy (cheapest to most expensive):
  1. Exact / case-insensitive match on canonical_name or any alias within the same type.
  2. Trigram similarity (pg_trgm) on canonical_name >= SIM_TRIGRAM within same type.
  3. Cosine similarity on embedding of "{name} ({type})\n{description}\ncontext: {context}"
     vs existing entity embeddings, same type, >= SIM_EMBED.
  4. If one strong candidate survives, merge (add the new name as an alias if different).
  5. If multiple candidates survive, one LLM disambiguation call picks the winner.
     Tool use when the provider supports it (no parsing fragility); falls back to a
     letter-pick JSON game otherwise.
  6. Else create a new entity with the computed embedding.

Type-scoped: a person "Kato" never merges with a project "Kato AI" — types are
separate namespaces. If the mention's type is empty, we treat it as "topic" so the
entity is still useful downstream.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from m3.core.engines.base import EntityMention
from m3.core.llm import EmbeddingProvider, LLMProvider, Tool
from m3.storage.models import Entity

logger = logging.getLogger("m3.entity_resolver")

SIM_TRIGRAM = 0.50
SIM_EMBED = 0.78
SIM_AUTO_MERGE = 0.88
MAX_CANDIDATES = 5
DEFAULT_TYPE = "topic"


@dataclass
class ResolutionOutcome:
    entity: Entity
    method: str       # exact | alias | trigram_auto | embed_auto | llm_match | llm_none | new
    confidence: float


def _embed_text_for(mention: EntityMention) -> str:
    parts = [mention.canonical_name, f"({mention.entity_type})"]
    if mention.description:
        parts.append(mention.description)
    if mention.context:
        parts.append(f"context: {mention.context[:240]}")
    return "\n".join(parts)


async def _find_exact(
    session: AsyncSession, name: str, entity_type: str
) -> Entity | None:
    """Case-insensitive match on canonical_name. Aliases checked separately to
    keep the SQL portable across drivers."""
    lowered = name.lower()
    stmt = (
        select(Entity)
        .where(Entity.entity_type == entity_type)
        .where(func.lower(Entity.canonical_name) == lowered)
        .limit(1)
    )
    result = await session.execute(stmt)
    ent = result.scalar_one_or_none()
    if ent is not None:
        return ent

    # Alias path: check the aliases array. We use a small scan scoped to type
    # which is fine at this repo's scale (type-scoped entity counts stay small).
    stmt_alias = select(Entity).where(Entity.entity_type == entity_type).where(
        Entity.aliases.isnot(None)
    )
    rows = (await session.execute(stmt_alias)).scalars().all()
    for e in rows:
        if any(a.lower() == lowered for a in (e.aliases or [])):
            return e
    return None


async def _find_trigram_candidates(
    session: AsyncSession, name: str, entity_type: str, limit: int
) -> list[tuple[Entity, float]]:
    stmt = text(
        """
        SELECT id, similarity(canonical_name, :name) AS sim
        FROM entities
        WHERE entity_type = :etype
          AND canonical_name % :name
        ORDER BY sim DESC
        LIMIT :lim
        """
    )
    rows = (await session.execute(stmt, {"name": name, "etype": entity_type, "lim": limit})).all()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    sims = {r[0]: float(r[1]) for r in rows}
    ents = (await session.execute(select(Entity).where(Entity.id.in_(ids)))).scalars().all()
    ents_by_id = {e.id: e for e in ents}
    return [(ents_by_id[i], sims[i]) for i in ids if i in ents_by_id]


async def _find_embedding_candidates(
    session: AsyncSession,
    embedding: list[float],
    entity_type: str,
    limit: int,
) -> list[tuple[Entity, float]]:
    cosine_distance = Entity.embedding.cosine_distance(embedding)
    stmt = (
        select(Entity, cosine_distance.label("dist"))
        .where(Entity.entity_type == entity_type)
        .where(Entity.embedding.isnot(None))
        .order_by(cosine_distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(ent, max(0.0, 1.0 - float(dist))) for ent, dist in rows]


def _merge_candidates(
    trigram: list[tuple[Entity, float]],
    embed: list[tuple[Entity, float]],
) -> list[tuple[Entity, float]]:
    by_id: dict = {}
    for ent, tri in trigram:
        by_id[ent.id] = {"ent": ent, "tri": tri, "emb": 0.0}
    for ent, emb in embed:
        if ent.id in by_id:
            by_id[ent.id]["emb"] = emb
        else:
            by_id[ent.id] = {"ent": ent, "tri": 0.0, "emb": emb}
    merged = []
    for rec in by_id.values():
        combined = 0.4 * rec["tri"] + 0.6 * rec["emb"]
        merged.append((rec["ent"], combined))
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged[:MAX_CANDIDATES]


async def _llm_disambiguate_tool(
    llm: LLMProvider,
    mention: EntityMention,
    candidates: list[tuple[Entity, float]],
) -> int | None:
    """Tool-use disambiguation. Model is forced to invoke one of two tools:
    pick_entity (with an index in [0, len(candidates))) or decide_none.
    Schema-valid by construction — no parsing fragility."""
    lines = []
    for i, (ent, score) in enumerate(candidates):
        alias_str = f", aka: {', '.join(ent.aliases or [])}" if ent.aliases else ""
        desc_str = f" -- {ent.description}" if ent.description else ""
        lines.append(
            f"[{i}] {ent.canonical_name} ({ent.entity_type}){alias_str}{desc_str} "
            f"[score {score:.2f}]"
        )

    system = (
        "You disambiguate named entities in a personal knowledge base. "
        "Call pick_entity only when you are confident the mention is the "
        "same entity as one of the candidates. Otherwise call decide_none."
    )
    user = (
        f"Mention: \"{mention.canonical_name}\" ({mention.entity_type})\n"
        f"Context: \"{(mention.context or '')[:300]}\"\n\n"
        f"Candidates:\n" + "\n".join(lines)
    )
    tools = [
        Tool(
            name="pick_entity",
            description="Mention is the same entity as the candidate at index.",
            input_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 0, "maximum": len(candidates) - 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["index", "confidence"],
            },
        ),
        Tool(
            name="decide_none",
            description="None of the candidates match; create a new entity.",
            input_schema={
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": [],
            },
        ),
    ]
    try:
        result = await llm.complete_tool(
            messages=[{"role": "user", "content": user}],
            tools=tools,
            system=system,
            max_tokens=256,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning(f"Tool-use disambiguation failed: {e}; treating as NONE")
        return None

    if result.tool_name == "pick_entity":
        idx = result.input.get("index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            return idx
    return None


async def _llm_disambiguate_letters(
    llm: LLMProvider,
    mention: EntityMention,
    candidates: list[tuple[Entity, float]],
) -> int | None:
    """Fallback disambiguation for providers without tool support."""
    lines = []
    for i, (ent, score) in enumerate(candidates):
        alias_str = f", aka: {', '.join(ent.aliases or [])}" if ent.aliases else ""
        desc_str = f" -- {ent.description}" if ent.description else ""
        lines.append(
            f"{chr(65 + i)}) {ent.canonical_name} ({ent.entity_type}){alias_str}{desc_str} "
            f"[score {score:.2f}]"
        )
    lines.append(f"{chr(65 + len(candidates))}) None of the above")

    system = (
        "You disambiguate named entities in a personal knowledge base. "
        "Reply with JSON only: {\"choice\": \"A\"} or {\"choice\": \"B\"} etc, "
        "or {\"choice\": \"NONE\"} if none apply."
    )
    user = (
        f"Mention: \"{mention.canonical_name}\" ({mention.entity_type})\n"
        f"Context: \"{(mention.context or '')[:300]}\"\n\n"
        f"Candidates:\n" + "\n".join(lines) + "\n\nReply JSON only."
    )
    try:
        resp = await llm.complete(
            messages=[{"role": "user", "content": user}],
            system=system,
            max_tokens=64,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning(f"Letter disambiguation failed: {e}; treating as NONE")
        return None

    try:
        text_stripped = resp.strip()
        data = json.loads(text_stripped) if text_stripped.startswith("{") else {}
    except Exception:
        m = re.search(r"choice[^A-Z]*([A-Z])", resp)
        data = {"choice": m.group(1)} if m else {}

    choice = (data.get("choice") or "").strip().upper()
    if choice in ("NONE", "N", ""):
        return None
    if len(choice) == 1 and "A" <= choice <= "Z":
        idx = ord(choice) - ord("A")
        if 0 <= idx < len(candidates):
            return idx
    return None


async def resolve(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    mention: EntityMention,
) -> ResolutionOutcome:
    """Resolve a mention to an existing entity or create a new one."""
    name = (mention.canonical_name or "").strip()
    if not name:
        raise ValueError("EntityMention.canonical_name is required")
    entity_type = (mention.entity_type or DEFAULT_TYPE).strip().lower()

    # Layer 1: exact / alias
    exact = await _find_exact(session, name, entity_type)
    if exact is not None:
        return ResolutionOutcome(entity=exact, method="exact", confidence=1.0)

    embed_text = _embed_text_for(mention)
    try:
        vector = (await embedder.embed([embed_text]))[0]
    except Exception as e:
        logger.warning(f"Embedding failed for '{name}': {e}")
        vector = None

    # Layer 2+3: trigram + embedding
    tri = await _find_trigram_candidates(session, name, entity_type, MAX_CANDIDATES)
    emb = await _find_embedding_candidates(session, vector, entity_type, MAX_CANDIDATES) if vector is not None else []
    candidates = _merge_candidates(
        [(e, s) for e, s in tri if s >= SIM_TRIGRAM],
        [(e, s) for e, s in emb if s >= SIM_EMBED],
    )

    # Layer 4: auto-merge
    if len(candidates) == 1 and candidates[0][1] >= SIM_AUTO_MERGE:
        ent, score = candidates[0]
        _add_alias_if_new(ent, name)
        return ResolutionOutcome(
            entity=ent,
            method="embed_auto" if emb else "trigram_auto",
            confidence=score,
        )

    # Layer 5: LLM disambiguation
    if len(candidates) >= 1:
        if llm.supports_tools:
            pick = await _llm_disambiguate_tool(llm, mention, candidates)
        else:
            pick = await _llm_disambiguate_letters(llm, mention, candidates)
        if pick is not None:
            ent, score = candidates[pick]
            _add_alias_if_new(ent, name)
            return ResolutionOutcome(entity=ent, method="llm_match", confidence=max(score, 0.6))

    # Layer 6: new entity
    new_ent = Entity(
        canonical_name=name,
        entity_type=entity_type,
        aliases=list(mention.aliases or []),
        description=mention.description,
        embedding=vector,
        resolution_method="new",
        resolution_confidence=1.0,
    )
    session.add(new_ent)
    await session.flush()
    return ResolutionOutcome(entity=new_ent, method="new", confidence=1.0)


def _add_alias_if_new(ent: Entity, name: str) -> None:
    lowered = name.lower()
    existing_aliases = {a.lower() for a in (ent.aliases or [])}
    if lowered == ent.canonical_name.lower() or lowered in existing_aliases:
        return
    ent.aliases = [*(ent.aliases or []), name]
