"""
M3 Ingest API — capture content from any source.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import get_db, get_files, verify_auth
from m3.schemas.api import IngestResponse, PaginatedResponse, RawItemResponse
from m3.storage.files import FileStore
from m3.storage.models import RawItem

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


_EXT_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pptx": "pptx",
    ".ppt": "pptx",
    ".epub": "epub",
    ".html": "html",
    ".htm": "html",
}


def _content_type_from_mime(mime: str, filename: str | None = None) -> str:
    """Map MIME type (with filename fallback) to M3 content type."""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        return "docx"
    if mime in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return "xlsx"
    if mime in (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
    ):
        return "pptx"
    if mime == "application/epub+zip":
        return "epub"
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    if mime.startswith("text/"):
        return "file"
    # Fallback to extension when MIME is generic
    if filename:
        name = filename.lower()
        for ext, ctype in _EXT_TO_TYPE.items():
            if name.endswith(ext):
                return ctype
    return "file"


@router.post("", response_model=IngestResponse, status_code=201)
async def ingest_json(
    content_text: str | None = Form(None),
    content_url: str | None = Form(None),
    tags: str | None = Form(None),
    project: str | None = Form(None),
    source_channel: str = Form("api"),
    file: UploadFile | None = File(None),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    """Ingest content -- text, URL, or file upload."""
    item_id = uuid.uuid4()
    file_path = None
    content_type = "text"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    if file:
        content_type = _content_type_from_mime(
            file.content_type or "application/octet-stream",
            file.filename,
        )
        file_data = await file.read()
        file_path = f"raw/{item_id}/{file.filename}"
        await files.upload(file_path, file_data, file.content_type or "application/octet-stream")
    elif content_url:
        content_type = "url"
        content_text = content_url
    elif not content_text:
        content_type = "text"
        content_text = ""

    item = RawItem(
        id=item_id,
        content_text=content_text,
        content_type=content_type,
        source_channel=source_channel,
        file_path=file_path,
        user_tags=tag_list,
        user_project=project,
    )
    db.add(item)
    await db.flush()

    # Enqueue processing job
    if hasattr(request.app.state, "arq_pool"):
        await request.app.state.arq_pool.enqueue_job("process_item", str(item_id))

    return IngestResponse(id=item_id, status="pending", message="Item queued for processing")


@router.get("", response_model=PaginatedResponse[RawItemResponse])
async def list_items(
    status: str | None = Query(None),
    source_channel: str | None = Query(None),
    project: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    files: FileStore = Depends(get_files),
    _auth: str = Depends(verify_auth),
):
    """List raw items with optional filters."""
    query = select(RawItem).order_by(RawItem.created_at.desc())
    count_query = select(func.count(RawItem.id))

    if status:
        query = query.where(RawItem.status == status)
        count_query = count_query.where(RawItem.status == status)
    if source_channel:
        query = query.where(RawItem.source_channel == source_channel)
        count_query = count_query.where(RawItem.source_channel == source_channel)
    if project:
        query = query.where(RawItem.user_project == project)
        count_query = count_query.where(RawItem.user_project == project)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    items = result.scalars().all()

    item_responses = []
    for item in items:
        file_url = None
        if item.file_path:
            file_url = await files.get_url(item.file_path)
        item_responses.append(
            RawItemResponse(
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
                processed_at=item.processed_at,
            )
        )

    return PaginatedResponse(items=item_responses, total=total, page=page, per_page=per_page)
