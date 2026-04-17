"""
M3 Insights API — Phase 4 read + status endpoints.

GET /api/v1/insights — paginated feed, optional status filter.
PATCH /api/v1/insights/{id} — flip status to acknowledged / dismissed / new.

No create endpoint. Insights are engine-emitted after every entity-mode
ingest.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.schemas.api import (
    InsightPatchRequest,
    InsightSummary,
    PaginatedResponse,
)
from m3.storage.models import Insight

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])

_VALID_STATUSES = {"new", "acknowledged", "dismissed"}


@router.get("", response_model=PaginatedResponse[InsightSummary])
async def list_insights(
    status: str | None = Query(None, description="Filter by status"),
    insight_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    base = select(Insight)
    if status:
        if status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status {status!r}")
        base = base.where(Insight.status == status)
    if insight_type:
        base = base.where(Insight.insight_type == insight_type.lower())

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    offset = (page - 1) * per_page
    stmt = (
        base.order_by(Insight.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [_to_summary(r) for r in rows]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.patch("/{insight_id}", response_model=InsightSummary)
async def patch_insight(
    insight_id: uuid.UUID,
    body: InsightPatchRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status {body.status!r}")
    row = await db.get(Insight, insight_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    row.status = body.status
    await db.flush()
    return _to_summary(row)


def _to_summary(r: Insight) -> InsightSummary:
    return InsightSummary(
        id=r.id,
        insight_type=r.insight_type,
        title=r.title,
        description=r.description,
        related_entity_ids=list(r.related_entity_ids or []),
        related_item_ids=list(r.related_item_ids or []),
        status=r.status,
        created_at=r.created_at,
    )
