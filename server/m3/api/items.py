"""HTTP surface for item meta + original bytes."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from m3.brain.items import read_meta
from m3.brain.layout import BrainPaths


class ItemMetaModel(BaseModel):
    id: str
    kind: str
    source: str
    created_at: str
    original_filename: str | None = None
    extracted_text: str
    when_iso: str | None = None
    when_source: str
    hooks: dict
    confidence: float


def build_items_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["items"])

    @router.get("/items/{item_id}", response_model=ItemMetaModel)
    async def get_item(item_id: str):
        try:
            uid = uuid.UUID(item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid uuid")
        meta = read_meta(brain_root, uid)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found")
        return ItemMetaModel(
            id=str(meta.id),
            kind=meta.kind,
            source=meta.source,
            created_at=meta.created_at,
            original_filename=meta.original_filename,
            extracted_text=meta.extracted_text,
            when_iso=meta.when_iso,
            when_source=meta.when_source,
            hooks=meta.hooks,
            confidence=meta.confidence,
        )

    @router.get("/items/{item_id}/original")
    async def get_item_original(item_id: str):
        try:
            uid = uuid.UUID(item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid uuid")
        p = BrainPaths(brain_root)
        candidates = list(p.items_originals.glob(f"{uid}.*"))
        if not candidates:
            raise HTTPException(status_code=404, detail=f"no original bytes for {item_id}")
        return FileResponse(candidates[0])

    return router
