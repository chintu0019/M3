"""
M3 Library API -- browse, retry, delete, annotate ingested items.

Separated from ingest.py which keeps the upload-side POST endpoints.
Both routers mount under /api/v1/ingest.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, get_files, verify_auth
from m3.schemas.api import (
    BulkIdsRequest,
    BulkOpError,
    BulkOpResult,
    CountItem,
    ItemDetailResponse,
    ItemNoteCreate,
    ItemNoteResponse,
    ItemNoteUpdate,
    ItemPatchRequest,
    LibraryStatsResponse,
    WikiPageLinkedToItem,
)
from m3.storage.files import FileStore
from m3.storage.models import ItemNote, RawItem, WikiPage

logger = logging.getLogger("m3.library")

router = APIRouter(prefix="/api/v1/ingest", tags=["library"])


async def _build_detail_response(
    item: RawItem, db: AsyncSession, files: FileStore
) -> ItemDetailResponse:
    # Notes (chronological)
    notes_result = await db.execute(
        select(ItemNote).where(ItemNote.item_id == item.id).order_by(ItemNote.created_at)
    )
    notes = [
        ItemNoteResponse(
            id=n.id,
            item_id=n.item_id,
            content=n.content,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in notes_result.scalars().all()
    ]

    # Linked wiki pages (any wiki page that includes this item.id in source_items)
    linked_result = await db.execute(
        select(WikiPage)
        .where(WikiPage.source_items.any(item.id))
        .where(WikiPage.page_type != "_index")
    )
    linked_pages = [
        WikiPageLinkedToItem(
            id=p.id,
            title=p.title,
            category=p.category,
            page_type=p.page_type,
            tags=p.tags or [],
            confidence=p.confidence,
            updated_at=p.updated_at,
        )
        for p in linked_result.scalars().all()
    ]

    file_url = await files.get_url(item.file_path) if item.file_path else None

    return ItemDetailResponse(
        id=item.id,
        content_text=item.content_text,
        content_type=item.content_type,
        source_channel=item.source_channel,
        source_metadata=item.source_metadata or {},
        file_path=item.file_path,
        file_url=file_url,
        user_tags=item.user_tags or [],
        user_project=item.user_project,
        status=item.status,
        error_message=item.error_message,
        created_at=item.created_at,
        processing_started_at=item.processing_started_at,
        processed_at=item.processed_at,
        notes=notes,
        linked_wiki_pages=linked_pages,
    )


# --- Static-path routes first (must precede /{item_id} to avoid UUID coercion clash) ---


@router.post("/bulk/retry", response_model=BulkOpResult)
async def bulk_retry(
    body: BulkIdsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    result = BulkOpResult()
    pool = request.app.state.arq_pool
    for item_id in body.ids:
        try:
            item = await db.get(RawItem, item_id)
            if not item:
                result.failed.append(BulkOpError(id=str(item_id), error="not_found"))
                continue
            if item.status == "processing":
                result.failed.append(BulkOpError(id=str(item_id), error="already_processing"))
                continue
            item.status = "pending"
            item.error_message = None
            item.processing_started_at = None
            item.processed_at = None
            await db.flush()
            await pool.enqueue_job("process_item", str(item_id))
            result.succeeded.append(item_id)
        except Exception as e:
            result.failed.append(BulkOpError(id=str(item_id), error=str(e)))
    return result


@router.post("/bulk/delete", response_model=BulkOpResult)
async def bulk_delete(
    body: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    result = BulkOpResult()
    for item_id in body.ids:
        try:
            item = await db.get(RawItem, item_id)
            if not item:
                result.failed.append(BulkOpError(id=str(item_id), error="not_found"))
                continue
            stored_path = item.file_path
            if stored_path:
                try:
                    await files.delete(stored_path)
                except Exception as e:
                    logger.warning(f"Failed to delete file for item {item_id} ({stored_path}): {e}")
            await db.delete(item)
            await db.flush()
            result.succeeded.append(item_id)
        except Exception as e:
            result.failed.append(BulkOpError(id=str(item_id), error=str(e)))
    return result


_DOC_TYPES = {"pdf", "docx", "xlsx", "pptx", "epub", "html"}


def _type_bucket(content_type: str | None) -> str:
    if not content_type:
        return "text"
    if content_type in _DOC_TYPES or content_type == "file":
        return "documents"
    if content_type == "image":
        return "images"
    if content_type in ("audio", "voice"):
        return "audio"
    if content_type == "video":
        return "video"
    if content_type == "url":
        return "links"
    return "text"


@router.get("/library/stats", response_model=LibraryStatsResponse)
async def library_stats(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    # Totals by status
    status_rows = (
        await db.execute(select(RawItem.status, func.count(RawItem.id)).group_by(RawItem.status))
    ).all()
    totals = {"all": 0, "recent": 0, "pending": 0, "processing": 0, "done": 0, "error": 0}
    for status, count in status_rows:
        totals[status] = count
        totals["all"] += count

    # Recent (last 24h)
    recent_row = (
        await db.execute(
            select(func.count(RawItem.id)).where(
                RawItem.created_at >= func.now() - text("interval '24 hours'")
            )
        )
    ).scalar()
    totals["recent"] = recent_row or 0

    # Projects (user_project, skip null)
    project_rows = (
        await db.execute(
            select(RawItem.user_project, func.count(RawItem.id))
            .where(RawItem.user_project.isnot(None))
            .group_by(RawItem.user_project)
            .order_by(func.count(RawItem.id).desc())
        )
    ).all()
    projects = [CountItem(key=p, count=c) for p, c in project_rows]

    # Unassigned project count
    unassigned = (
        await db.execute(select(func.count(RawItem.id)).where(RawItem.user_project.is_(None)))
    ).scalar()
    if unassigned:
        projects.append(CountItem(key="(Unassigned)", count=unassigned))

    # Types (bucket content_types)
    type_rows = (
        await db.execute(select(RawItem.content_type, func.count(RawItem.id)).group_by(RawItem.content_type))
    ).all()
    buckets: dict[str, int] = {}
    for ct, count in type_rows:
        bucket = _type_bucket(ct)
        buckets[bucket] = buckets.get(bucket, 0) + count
    types = [CountItem(key=k, count=v) for k, v in sorted(buckets.items())]

    # Sources
    source_rows = (
        await db.execute(
            select(RawItem.source_channel, func.count(RawItem.id))
            .where(RawItem.source_channel.isnot(None))
            .group_by(RawItem.source_channel)
            .order_by(func.count(RawItem.id).desc())
        )
    ).all()
    sources = [CountItem(key=s, count=c) for s, c in source_rows]

    return LibraryStatsResponse(totals=totals, projects=projects, types=types, sources=sources)


# --- Parameterized routes (/{item_id} and sub-paths) ---


@router.get("/{item_id}", response_model=ItemDetailResponse)
async def get_item_detail(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    item = await db.get(RawItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return await _build_detail_response(item, db, files)


@router.patch("/{item_id}", response_model=ItemDetailResponse)
async def patch_item(
    item_id: uuid.UUID,
    body: ItemPatchRequest,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    item = await db.get(RawItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if body.user_tags is not None:
        item.user_tags = body.user_tags
    if body.user_project is not None:
        item.user_project = body.user_project or None
    if body.filename is not None:
        fname = body.filename.strip()
        if not fname:
            raise HTTPException(status_code=400, detail="filename cannot be empty")
        if "/" in fname:
            raise HTTPException(status_code=400, detail="filename cannot contain '/'")
        if item.file_path:
            parts = item.file_path.split("/")
            old_path = item.file_path
            parts[-1] = fname
            new_path = "/".join(parts)
            try:
                await files.rename(old_path, new_path)
            except Exception as e:
                logger.error(f"MinIO rename failed {old_path} -> {new_path}: {e}")
                raise HTTPException(status_code=500, detail="File rename failed; database not updated")
            item.file_path = new_path

    await db.flush()
    return await _build_detail_response(item, db, files)


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    item = await db.get(RawItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    stored_path = item.file_path

    if stored_path:
        try:
            await files.delete(stored_path)
        except Exception as e:
            # If the file is already gone from MinIO (e.g. eventual consistency),
            # continue so users aren't blocked from cleaning up stale DB rows.
            logger.warning(f"MinIO delete failed for {stored_path}: {e}")

    # Cascade deletes notes (via FK). Wiki pages referenced via source_items are not removed --
    # they may still be useful to the wiki and refer to the item id only.
    await db.delete(item)
    await db.flush()


@router.post("/{item_id}/retry", response_model=ItemDetailResponse)
async def retry_item(
    item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    item = await db.get(RawItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.status == "processing":
        raise HTTPException(status_code=409, detail="Item is currently processing")

    item.status = "pending"
    item.error_message = None
    item.processing_started_at = None
    item.processed_at = None
    await db.flush()

    pool = request.app.state.arq_pool
    await pool.enqueue_job("process_item", str(item_id))

    return await _build_detail_response(item, db, files)


def _note_to_response(note: ItemNote) -> ItemNoteResponse:
    return ItemNoteResponse(
        id=note.id,
        item_id=note.item_id,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.post("/{item_id}/notes", response_model=ItemNoteResponse, status_code=201)
async def create_note(
    item_id: uuid.UUID,
    body: ItemNoteCreate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    item = await db.get(RawItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    note = ItemNote(item_id=item_id, content=body.content)
    db.add(note)
    await db.flush()
    await db.refresh(note)

    return _note_to_response(note)


@router.patch("/{item_id}/notes/{note_id}", response_model=ItemNoteResponse)
async def update_note(
    item_id: uuid.UUID,
    note_id: uuid.UUID,
    body: ItemNoteUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    note = await db.get(ItemNote, note_id)
    if not note or note.item_id != item_id:
        raise HTTPException(status_code=404, detail="Note not found")

    note.content = body.content
    await db.flush()
    await db.refresh(note)

    return _note_to_response(note)


@router.delete("/{item_id}/notes/{note_id}", status_code=204)
async def delete_note(
    item_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    note = await db.get(ItemNote, note_id)
    if not note or note.item_id != item_id:
        raise HTTPException(status_code=404, detail="Note not found")

    await db.delete(note)
    await db.flush()
