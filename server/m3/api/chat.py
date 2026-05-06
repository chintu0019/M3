"""POST /api/v1/chat — SSE streaming agent chat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from m3.brain import chats as _chats
from m3.core.agent import run_agent
from m3.core.llm.unconfigured import UnconfiguredProvider
from m3.core.tools import BrainTools


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    session_id: str | None = None    # when set, the turn is persisted to ~/brain/chats/
    scope_item_id: str | None = None # when set, scope retrieval + pin context to this item


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

        llm = _get_llm()

        # Pre-flight: if no real provider could be built, short-circuit with a
        # structured event the UI renders as a Settings CTA. Avoids letting
        # UnconfiguredProvider's generic RuntimeError surface as a vague
        # "type: error" toast.
        if isinstance(llm, UnconfiguredProvider):
            reason = llm.reason

            async def unconfigured_gen():
                yield "data: " + json.dumps({"type": "unconfigured", "reason": reason}) + "\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(unconfigured_gen(), media_type="text/event-stream")

        tools = BrainTools(brain_root=brain_root, embedder=embedder, scope_item_id=body.scope_item_id)

        async def gen():
            collected_events: list[dict] = []
            final_text = ""
            error_text: str | None = None
            try:
                async for ev in run_agent(llm=llm, tools=tools,
                                          user_message=body.message, history=body.history):
                    payload = {
                        "type": ev.type, "content": ev.content,
                        "tool_name": ev.tool_name, "tool_input": ev.tool_input,
                        "tool_result": ev.tool_result,
                    }
                    collected_events.append(payload)
                    if ev.type == "final":
                        final_text = ev.content or ""
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
            except Exception as e:
                error_text = str(e)
                yield f"data: {json.dumps({'type': 'error', 'content': error_text})}\n\n"
            # Persist the full exchange if the caller opted in by passing a
            # session_id. Append user turn then assistant turn so the file
            # mirrors the on-screen order. Errors are captured as assistant
            # content so the session record isn't silent about failure.
            if body.session_id:
                try:
                    _chats.append_turn(brain_root, body.session_id, "user", body.message)
                    assistant_content = final_text or (f"(error) {error_text}" if error_text else "")
                    _chats.append_turn(
                        brain_root, body.session_id, "assistant",
                        assistant_content, events=collected_events,
                    )
                except OSError:
                    # Persistence failure must not break the chat stream.
                    pass
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
