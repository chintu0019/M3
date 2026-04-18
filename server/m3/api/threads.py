"""
M3 Chat Threads API — Phase C.

Threads are first-class objects: list, create, inspect, end.
The stream handler in ``chat.py`` writes messages into them and
upserts ``chat_thread_pages`` rows as entities are cited.
Crystallization (pushing a thread through the ingest pipeline)
lands in Phase D.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, verify_auth
from m3.schemas.api import (
    ChatMessageResponse,
    ChatThreadCreateRequest,
    ChatThreadDetail,
    ChatThreadSummary,
    PaginatedResponse,
    ThreadCrystallizeResponse,
)
from m3.storage.models import ChatMessage, ChatThread, ChatThreadPage, RawItem

logger = logging.getLogger("m3.threads")

router = APIRouter(prefix="/api/v1/chat/threads", tags=["chat-threads"])


def _build_summary(t: ChatThread, message_count: int) -> ChatThreadSummary:
    return ChatThreadSummary(
        id=t.id,
        title=t.title,
        summary=t.summary,
        status=t.status,
        created_at=t.created_at,
        ended_at=t.ended_at,
        crystallized_at=t.crystallized_at,
        message_count=message_count,
    )


async def _summary(db: AsyncSession, t: ChatThread) -> ChatThreadSummary:
    count = (
        await db.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.thread_id == t.id)
        )
    ).scalar_one()
    return _build_summary(t, int(count or 0))


@router.get("", response_model=PaginatedResponse[ChatThreadSummary])
async def list_threads(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    base = select(ChatThread)
    if status_filter:
        base = base.where(ChatThread.status == status_filter)
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (
        await db.execute(
            base.order_by(ChatThread.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()
    # Single aggregation query instead of N SELECT COUNT(*) round-trips.
    counts: dict[uuid.UUID, int] = {}
    if rows:
        thread_ids = [t.id for t in rows]
        count_rows = (
            await db.execute(
                select(ChatMessage.thread_id, func.count(ChatMessage.id))
                .where(ChatMessage.thread_id.in_(thread_ids))
                .group_by(ChatMessage.thread_id)
            )
        ).all()
        counts = {tid: int(c or 0) for tid, c in count_rows}
    items = [_build_summary(t, counts.get(t.id, 0)) for t in rows]
    return PaginatedResponse(
        items=items, total=int(total or 0), page=page, per_page=per_page
    )


@router.post("", response_model=ChatThreadSummary, status_code=201)
async def create_thread(
    body: ChatThreadCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    t = ChatThread(title=body.title)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return await _summary(db, t)


@router.get("/{thread_id}", response_model=ChatThreadDetail)
async def get_thread(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    t = await db.get(ChatThread, thread_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    msg_rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    cite_rows = (
        await db.execute(
            select(ChatThreadPage.entity_id).where(
                ChatThreadPage.thread_id == thread_id
            )
        )
    ).scalars().all()

    count = len(msg_rows)
    return ChatThreadDetail(
        id=t.id,
        title=t.title,
        summary=t.summary,
        status=t.status,
        created_at=t.created_at,
        ended_at=t.ended_at,
        crystallized_at=t.crystallized_at,
        message_count=count,
        messages=[
            ChatMessageResponse(
                id=m.id, role=m.role, content=m.content, created_at=m.created_at
            )
            for m in msg_rows
        ],
        cited_entity_ids=list(cite_rows),
    )


@router.post("/{thread_id}/end", response_model=ChatThreadSummary)
async def end_thread(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    t = await db.get(ChatThread, thread_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if t.status != "ended":
        t.status = "ended"
        t.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(t)
    return await _summary(db, t)


@router.post("/{thread_id}/crystallize", response_model=ThreadCrystallizeResponse)
async def crystallize_thread(
    thread_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    t = await db.get(ChatThread, thread_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if t.crystallized_at is not None:
        raise HTTPException(status_code=409, detail="Already crystallized")

    msg_rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()

    has_assistant = any(m.role == "assistant" and m.content.strip() for m in msg_rows)
    if not has_assistant:
        raise HTTPException(
            status_code=400, detail="Thread has no assistant response to crystallize"
        )

    transcript = "\n\n".join(
        f"{m.role.upper()}: {m.content.strip()}" for m in msg_rows if m.content.strip()
    )

    raw_item = RawItem(
        content_text=transcript,
        content_type="conversation",
        source_channel="chat",
        source_metadata={"thread_id": str(thread_id), "title": t.title},
        status="pending",
    )
    db.add(raw_item)
    if t.status != "ended":
        t.status = "ended"
        t.ended_at = datetime.now(timezone.utc)
    t.crystallized_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(raw_item)

    enqueued = False
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job("process_item", str(raw_item.id))
            enqueued = True
        except Exception as exc:  # pragma: no cover — surface, don't crash
            logger.warning("ARQ enqueue failed: %s", exc)
    else:
        logger.warning("No ARQ pool on app.state; relying on drain_pending_items")

    return ThreadCrystallizeResponse(
        thread_id=thread_id,
        raw_item_id=raw_item.id,
        enqueued=enqueued,
    )
