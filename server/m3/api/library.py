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
