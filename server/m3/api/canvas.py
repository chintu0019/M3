"""
M3 Canvas API — unified graph read + layout persistence.

Returns entities (page-capable or small chips) + insights, plus
entity_links as edges. Layout positions for each (node_type, node_id)
come from the canvas_layout table; absent rows mean "let the client
run its own force layout for this node."
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.schemas.api import (
    CanvasEdge,
    CanvasLayoutBulkRequest,
    CanvasLayoutBulkResponse,
    CanvasNode,
    CanvasResponse,
)
from m3.storage.models import CanvasLayout, Entity, EntityLink, Insight

router = APIRouter(prefix="/api/v1/canvas", tags=["canvas"])


def _entity_node_id(entity_id) -> str:
    return f"entity:{entity_id}"


def _insight_node_id(insight_id) -> str:
    return f"insight:{insight_id}"


@router.get("", response_model=CanvasResponse)
async def get_canvas(
    entity_limit: int = Query(500, ge=1, le=2000),
    include_insights: bool = Query(True),
    insight_status: str = Query("new"),
    include_threads: bool = Query(True),
    thread_limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    from m3.storage.models import ChatThread, ChatThreadPage  # local import to keep module header small

    entity_rows = (
        await db.execute(
            select(Entity)
            .order_by(Entity.facts_since_render.desc(), Entity.updated_at.desc())
            .limit(entity_limit)
        )
    ).scalars().all()
    entity_ids = {e.id for e in entity_rows}

    edge_rows = []
    if entity_ids:
        edge_rows = (
            await db.execute(
                select(EntityLink).where(
                    EntityLink.source_entity_id.in_(entity_ids),
                    EntityLink.target_entity_id.in_(entity_ids),
                )
            )
        ).scalars().all()

    insight_rows = []
    if include_insights:
        insight_rows = (
            await db.execute(
                select(Insight)
                .where(Insight.status == insight_status)
                .order_by(Insight.created_at.desc())
                .limit(200)
            )
        ).scalars().all()

    thread_rows = []
    thread_cite_rows = []
    if include_threads:
        thread_rows = (
            await db.execute(
                select(ChatThread)
                .where(ChatThread.status.in_(["active", "ended"]))
                .order_by(ChatThread.created_at.desc())
                .limit(thread_limit)
            )
        ).scalars().all()
        thread_ids = {t.id for t in thread_rows}
        if thread_ids and entity_ids:
            thread_cite_rows = (
                await db.execute(
                    select(ChatThreadPage).where(
                        ChatThreadPage.thread_id.in_(thread_ids),
                        ChatThreadPage.entity_id.in_(entity_ids),
                    )
                )
            ).scalars().all()

    node_keys = (
        [("entity", str(e.id)) for e in entity_rows]
        + [("insight", str(i.id)) for i in insight_rows]
        + [("thread", str(t.id)) for t in thread_rows]
    )
    layout_map: dict[tuple[str, str], CanvasLayout] = {}
    if node_keys:
        types = {k[0] for k in node_keys}
        ids = {k[1] for k in node_keys}
        layout_rows = (
            await db.execute(
                select(CanvasLayout).where(
                    CanvasLayout.node_type.in_(types),
                    CanvasLayout.node_id.in_(ids),
                )
            )
        ).scalars().all()
        layout_map = {(r.node_type, r.node_id): r for r in layout_rows}

    def _pos(node_type: str, node_id: str):
        row = layout_map.get((node_type, node_id))
        if row is None:
            return None, None, None, None
        return row.x, row.y, row.width, row.height

    nodes: list[CanvasNode] = []
    for e in entity_rows:
        x, y, w, h = _pos("entity", str(e.id))
        nodes.append(
            CanvasNode(
                id=_entity_node_id(e.id),
                node_type="entity",
                label=e.canonical_name,
                data={
                    "entity_type": e.entity_type,
                    "has_page": bool(e.page_content),
                    "overview": e.page_overview,
                    "facts_since_render": e.facts_since_render or 0,
                },
                x=x, y=y, width=w, height=h,
            )
        )
    for i in insight_rows:
        x, y, w, h = _pos("insight", str(i.id))
        nodes.append(
            CanvasNode(
                id=_insight_node_id(i.id),
                node_type="insight",
                label=i.title,
                data={
                    "insight_type": i.insight_type,
                    "description": i.description,
                    "status": i.status,
                },
                x=x, y=y, width=w, height=h,
            )
        )
    for t in thread_rows:
        x, y, w, h = _pos("thread", str(t.id))
        nodes.append(
            CanvasNode(
                id=f"thread:{t.id}",
                node_type="thread",
                label=t.title or "Untitled thread",
                data={
                    "status": t.status,
                    "created_at": t.created_at.isoformat(),
                    "ended_at": t.ended_at.isoformat() if t.ended_at else None,
                },
                x=x, y=y, width=w, height=h,
            )
        )

    edges = [
        CanvasEdge(
            id=f"link:{el.id}",
            source=_entity_node_id(el.source_entity_id),
            target=_entity_node_id(el.target_entity_id),
            edge_type=el.link_type,
            weight=float(el.weight or 1),
        )
        for el in edge_rows
    ]
    for ctp in thread_cite_rows:
        edges.append(
            CanvasEdge(
                id=f"cite:{ctp.thread_id}:{ctp.entity_id}",
                source=f"thread:{ctp.thread_id}",
                target=_entity_node_id(ctp.entity_id),
                edge_type="cited_by_thread",
                weight=float(ctp.citation_count or 1),
            )
        )

    return CanvasResponse(nodes=nodes, edges=edges)


@router.patch("/layout", response_model=CanvasLayoutBulkResponse)
async def patch_layout(
    body: CanvasLayoutBulkRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    if not body.updates:
        return CanvasLayoutBulkResponse(written=0)

    values = [
        {
            "node_type": u.node_type,
            "node_id": u.node_id,
            "x": u.x,
            "y": u.y,
            "width": u.width,
            "height": u.height,
            "z_index": u.z_index,
        }
        for u in body.updates
    ]
    stmt = pg_insert(CanvasLayout).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["node_type", "node_id"],
        set_={
            "x": stmt.excluded.x,
            "y": stmt.excluded.y,
            "width": stmt.excluded.width,
            "height": stmt.excluded.height,
            "z_index": stmt.excluded.z_index,
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return CanvasLayoutBulkResponse(written=len(values))
