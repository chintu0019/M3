"""
M3 Library API -- browse, retry, delete, annotate ingested items.

Separated from ingest.py which keeps the upload-side POST endpoints.
Both routers mount under /api/v1/ingest.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, get_files, verify_auth
from m3.schemas.api import (
    ItemDetailResponse,
    ItemNoteResponse,
    ItemPatchRequest,
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
