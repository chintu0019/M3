"""POST /api/v1/chat — SSE streaming agent chat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from m3.core.agent import run_agent
from m3.core.tools import BrainTools


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None


def build_chat_router(*, brain_root: Path, embedder: _Embedder, llm_factory: Callable | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["chat"])

    def _get_llm():
        if llm_factory is None:
            raise HTTPException(status_code=503, detail="no LLM configured")
        return llm_factory()

    @router.post("/chat")
    async def chat(body: ChatRequest):
        if not body.message.strip():
            raise HTTPException(status_code=422, detail="message is required")

        tools = BrainTools(brain_root=brain_root, embedder=embedder)
        llm = _get_llm()

        async def gen():
            try:
                async for ev in run_agent(llm=llm, tools=tools,
                                          user_message=body.message, history=body.history):
                    payload = {
                        "type": ev.type, "content": ev.content,
                        "tool_name": ev.tool_name, "tool_input": ev.tool_input,
                        "tool_result": ev.tool_result,
                    }
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
