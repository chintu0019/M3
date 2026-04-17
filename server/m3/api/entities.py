"""
M3 Entities API — Phase 3 read-only endpoints for entity pages.

Minimal surface: list + detail. Phase 4 grows this with insight feed,
filtering, and search. For now it's just enough to fetch a rendered
entity page via HTTP so smoke tests and a future UI don't have to
psql the database.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.schemas.api import (
    EntityCreateRequest,
    EntityDetail,
    EntityGraphEdge,
    EntityGraphNode,
    EntityGraphResponse,
    EntityPatchRequest,
    EntitySummary,
    InsightSummary,
    PaginatedResponse,
    RelatedEntity,
)
from m3.storage.models import Entity, EntityFactLink, EntityLink, Insight

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


@router.get("", response_model=PaginatedResponse[EntitySummary])
async def list_entities(
    entity_type: str | None = Query(None, description="Filter by exact entity_type"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    base = select(Entity)
    if entity_type:
        base = base.where(Entity.entity_type == entity_type.lower())

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    offset = (page - 1) * per_page
    stmt = (
        base.order_by(Entity.updated_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        EntitySummary(
            id=e.id,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            aliases=list(e.aliases or []),
            updated_at=e.updated_at,
            has_page=bool(e.page_content),
            facts_since_render=e.facts_since_render or 0,
        )
        for e in rows
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/graph", response_model=EntityGraphResponse)
async def entity_graph(
    entity_type: str | None = Query(None, description="Filter nodes by entity_type"),
    limit: int = Query(300, ge=1, le=2000, description="Max nodes returned"),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """Node set: entities (optionally filtered by type), ordered by
    fact count desc, capped at `limit`. Edges: any entity_link whose
    endpoints both fall inside the node set."""
    # 1) Collect candidate nodes with fact counts in one query.
    fact_count = func.count(EntityFactLink.fact_id).label("fact_count")
    node_stmt = (
        select(
            Entity.id, Entity.canonical_name, Entity.entity_type, fact_count,
        )
        .outerjoin(EntityFactLink, EntityFactLink.entity_id == Entity.id)
        .group_by(Entity.id, Entity.canonical_name, Entity.entity_type)
        .order_by(fact_count.desc(), Entity.updated_at.desc())
        .limit(limit)
    )
    if entity_type:
        node_stmt = node_stmt.where(Entity.entity_type == entity_type.lower())

    rows = (await db.execute(node_stmt)).all()
    nodes = [
        EntityGraphNode(
            id=r[0], canonical_name=r[1], entity_type=r[2], fact_count=int(r[3] or 0),
        )
        for r in rows
    ]
    node_ids = {n.id for n in nodes}

    # 2) Edges between surviving nodes only.
    edges: list[EntityGraphEdge] = []
    if node_ids:
        edge_stmt = select(
            EntityLink.source_entity_id, EntityLink.target_entity_id,
            EntityLink.link_type, EntityLink.weight,
        ).where(
            EntityLink.source_entity_id.in_(node_ids),
            EntityLink.target_entity_id.in_(node_ids),
        )
        for src, tgt, lt, w in (await db.execute(edge_stmt)).all():
            edges.append(EntityGraphEdge(
                source_id=src, target_id=tgt, link_type=lt, weight=w or 1,
            ))

    return EntityGraphResponse(nodes=nodes, edges=edges)


@router.get("/{entity_id}", response_model=EntityDetail)
async def get_entity(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    ent = await db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Bidirectional related: edges in either direction, deduped by (name, link_type)
    # keeping the max weight. Same logic the renderer uses, intentionally.
    out_stmt = (
        select(
            Entity.id, Entity.canonical_name, Entity.entity_type,
            EntityLink.link_type, EntityLink.weight,
        )
        .join(EntityLink, EntityLink.target_entity_id == Entity.id)
        .where(EntityLink.source_entity_id == entity_id)
    )
    in_stmt = (
        select(
            Entity.id, Entity.canonical_name, Entity.entity_type,
            EntityLink.link_type, EntityLink.weight,
        )
        .join(EntityLink, EntityLink.source_entity_id == Entity.id)
        .where(EntityLink.target_entity_id == entity_id)
    )
    rows = list((await db.execute(out_stmt)).all()) + list((await db.execute(in_stmt)).all())

    dedup: dict[tuple[uuid.UUID, str], RelatedEntity] = {}
    for rid, rname, rtype, link_type, weight in rows:
        key = (rid, link_type)
        prev = dedup.get(key)
        if prev is None or prev.weight < (weight or 0):
            dedup[key] = RelatedEntity(
                id=rid, canonical_name=rname, entity_type=rtype,
                link_type=link_type, weight=weight or 0,
            )
    related = sorted(dedup.values(), key=lambda r: r.weight, reverse=True)[:10]

    # Open insights referencing this entity (new or acknowledged; dismissed
    # intentionally excluded from the entity page).
    insights_stmt = (
        select(Insight)
        .where(Insight.status.in_(["new", "acknowledged"]))
        .where(Insight.related_entity_ids.any(entity_id))
        .order_by(Insight.created_at.desc())
    )
    insight_rows = (await db.execute(insights_stmt)).scalars().all()
    insights = [
        InsightSummary(
            id=r.id,
            insight_type=r.insight_type,
            title=r.title,
            description=r.description,
            related_entity_ids=list(r.related_entity_ids or []),
            related_item_ids=list(r.related_item_ids or []),
            status=r.status,
            created_at=r.created_at,
        )
        for r in insight_rows
    ]

    return EntityDetail(
        id=ent.id,
        canonical_name=ent.canonical_name,
        entity_type=ent.entity_type,
        aliases=list(ent.aliases or []),
        description=ent.description,
        page_content=ent.page_content,
        page_overview=ent.page_overview,
        page_dirty=ent.page_dirty,
        facts_since_render=ent.facts_since_render or 0,
        created_at=ent.created_at,
        updated_at=ent.updated_at,
        related=related,
        insights=insights,
    )


@router.post("", response_model=EntityDetail, status_code=status.HTTP_201_CREATED)
async def create_entity(
    body: EntityCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    ent = Entity(
        canonical_name=body.canonical_name.strip(),
        entity_type=body.entity_type.strip().lower(),
        description=body.description,
    )
    db.add(ent)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Entity with this canonical_name + entity_type already exists",
        )
    await db.refresh(ent)
    return EntityDetail(
        id=ent.id,
        canonical_name=ent.canonical_name,
        entity_type=ent.entity_type,
        aliases=list(ent.aliases or []),
        description=ent.description,
        page_content=ent.page_content,
        page_overview=ent.page_overview,
        page_dirty=ent.page_dirty,
        facts_since_render=ent.facts_since_render or 0,
        created_at=ent.created_at,
        updated_at=ent.updated_at,
        related=[],
        insights=[],
    )


@router.patch("/{entity_id}", response_model=EntityDetail)
async def patch_entity(
    entity_id: uuid.UUID,
    body: EntityPatchRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    ent = await db.get(Entity, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    if body.canonical_name is not None:
        ent.canonical_name = body.canonical_name.strip()
    if body.description is not None:
        ent.description = body.description
    if body.page_content is not None:
        ent.page_content = body.page_content
        ent.page_dirty = False  # user-authored edit is the new source of truth
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Another entity with this canonical_name + entity_type exists",
        )
    await db.refresh(ent)
    # Return the same shape as GET — reuse get_entity so related/insights stay in sync.
    return await get_entity(entity_id=ent.id, db=db, _auth="")
