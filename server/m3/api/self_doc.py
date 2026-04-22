"""HTTP surface for reading self.md."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from m3.brain.layout import SELF_SLOTS
from m3.brain.self_doc import read_section


class SelfResponse(BaseModel):
    slots: dict[str, str]


def build_self_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["self"])

    @router.get("/self", response_model=SelfResponse)
    async def get_self():
        return SelfResponse(slots={slot: read_section(brain_root, slot) for slot in SELF_SLOTS})

    return router
