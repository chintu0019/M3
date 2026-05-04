"""HTTP surface for persisted chat sessions."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from m3.brain import chats as _chats


class SessionSummary(BaseModel):
    id: str
    title: str
    message_count: int
    last_ts: str


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

    return router
