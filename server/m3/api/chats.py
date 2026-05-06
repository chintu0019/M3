"""HTTP surface for persisted chat sessions and folders."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from m3.brain import chats as _chats
from m3.brain import folders as _folders


class SessionSummary(BaseModel):
    id: str
    title: str
    title_locked: bool = False
    message_count: int
    last_ts: str
    pinned: bool = False
    folder_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SessionTurn(BaseModel):
    ts: str
    role: str
    content: str
    events: list = []


class NewSessionResponse(BaseModel):
    id: str


class SessionResponse(BaseModel):
    id: str
    turns: list[SessionTurn]


class PatchSessionRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    folder_id: Optional[str] = None  # explicit None means "remove from folder"

    # Pydantic v2: distinguish "field not sent" from "sent as null".
    model_config = {"extra": "ignore"}


class FolderRecord(BaseModel):
    id: str
    name: str
    sort_order: int


class CreateFolderRequest(BaseModel):
    name: str


class PatchFolderRequest(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None


def build_chats_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["chats"])

    @router.get("/chats", response_model=list[SessionSummary])
    async def list_chats():
        return _chats.list_sessions(brain_root)

    @router.post("/chats", response_model=NewSessionResponse)
    async def new_chat():
        return NewSessionResponse(id=_chats.new_session(brain_root))

    @router.get("/chats/{sid}", response_model=SessionResponse)
    async def get_chat(sid: str):
        turns = _chats.load_session(brain_root, sid)
        if not turns:
            raise HTTPException(status_code=404, detail="session not found or empty")
        return SessionResponse(id=sid, turns=[SessionTurn(**t) for t in turns])

    @router.patch("/chats/{sid}", response_model=SessionSummary)
    async def patch_chat(sid: str, body: PatchSessionRequest):
        # Disallow patching a session that has no turns yet — the listing
        # would never show it anyway, and it makes the 404 unambiguous.
        if not _chats.load_session(brain_root, sid):
            raise HTTPException(status_code=404, detail="session not found or empty")
        update = body.model_dump(exclude_unset=True)
        meta = _chats.write_meta(brain_root, sid, **update)
        # Re-derive message_count + last_ts from the listing-style read for
        # response consistency.
        turns = _chats.load_session(brain_root, sid)
        return SessionSummary(
            id=sid,
            title=meta["title"],
            title_locked=meta["title_locked"],
            message_count=len(turns),
            last_ts=turns[-1]["ts"],
            pinned=meta["pinned"],
            folder_id=meta["folder_id"],
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
        )

    @router.delete("/chats/{sid}", status_code=204)
    async def delete_chat(sid: str):
        _chats.delete_session(brain_root, sid)
        return Response(status_code=204)

    @router.get("/folders", response_model=list[FolderRecord])
    async def list_folders():
        return _folders.list_folders(brain_root)

    @router.post("/folders", response_model=FolderRecord)
    async def create_folder(body: CreateFolderRequest):
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="name is required")
        return _folders.create_folder(brain_root, name=body.name.strip())

    @router.patch("/folders/{fid}", response_model=FolderRecord)
    async def patch_folder(fid: str, body: PatchFolderRequest):
        update = body.model_dump(exclude_unset=True)
        try:
            return _folders.update_folder(brain_root, fid, **update)
        except KeyError:
            raise HTTPException(status_code=404, detail="folder not found")

    @router.delete("/folders/{fid}", status_code=204)
    async def delete_folder(fid: str):
        _folders.delete_folder(brain_root, fid)
        # Orphan any chats that pointed at this folder back to no-folder so
        # the UI doesn't render dangling references.
        for s in _chats.list_sessions(brain_root):
            if s["folder_id"] == fid:
                _chats.write_meta(brain_root, s["id"], folder_id=None)
        return Response(status_code=204)

    return router
