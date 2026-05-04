"""HTTP surface for reading and editing self.md."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from m3.brain.layout import SELF_SLOTS
from m3.brain.self_doc import apply_update, read_section


class SelfResponse(BaseModel):
    slots: dict[str, str]


class SelfUpdateRequest(BaseModel):
    slot: str
    new_content: str


class SelfUpdateResponse(BaseModel):
    slot: str
    new_body: str


def build_self_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["self"])

    @router.get("/self", response_model=SelfResponse)
    async def get_self():
        return SelfResponse(slots={slot: read_section(brain_root, slot) for slot in SELF_SLOTS})

    @router.put("/self/{slot}", response_model=SelfUpdateResponse)
    async def update_self_section(slot: str, body: SelfUpdateRequest):
        if slot not in SELF_SLOTS:
            raise HTTPException(status_code=404, detail=f"unknown slot: {slot!r}")
        # apply_update has a special case where heading == slot name means
        # "replace the whole slot body" (including the empty-clear case).
        apply_update(
            brain_root,
            slot=slot,
            operation="replace_section",
            new_content=body.new_content,
            heading=slot,
        )
        return SelfUpdateResponse(slot=slot, new_body=body.new_content)

    return router
