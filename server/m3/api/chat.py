"""
M3 Chat API — streaming SSE chat grounded in the entity knowledge graph.

Phase C additions:
- Accept an optional ``thread_id``; if given, persist user + assistant
  turns into that thread and upsert chat_thread_pages when mentions
  resolve to known entities.
- Emit per-mention ``cite`` events during streaming so the canvas
  can pulse nodes and pan the viewport live.
"""

import json
import re
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.api.deps import verify_auth
from m3.core.search import SearchEngine
from m3.schemas.api import ChatRequest
from m3.storage.models import ChatMessage, ChatThread, ChatThreadPage, Entity

router = APIRouter(prefix="/api/v1", tags=["chat"])

MENTION_RE = re.compile(r"\[\[(.+?)\]\]")


def _format_context(entities: list[dict]) -> str:
    parts = []
    for e in entities:
        body = e.get("page_content") or e.get("page_overview") or e.get("description") or ""
        parts.append(f"### [[{e['name']}]] ({e['type']})\n{body}")
    return "\n\n---\n\n".join(parts)


async def _resolve_mention(
    db_factory: async_sessionmaker, name: str
) -> dict | None:
    key = name.lower().strip()
    async with db_factory() as session:
        row = (
            await session.execute(
                select(Entity.id, Entity.canonical_name, Entity.entity_type)
                .where(
                    or_(
                        func.lower(Entity.canonical_name) == key,
                        Entity.aliases.any(name),
                    )
                )
                .limit(1)
            )
        ).first()
    if row is None:
        return None
    return {
        "entity_id": str(row[0]),
        "name": row[1],
        "entity_type": row[2],
    }


async def _record_thread_citation(
    db_factory: async_sessionmaker, thread_id, entity_id
) -> None:
    async with db_factory() as session:
        stmt = pg_insert(ChatThreadPage).values(
            thread_id=thread_id,
            entity_id=entity_id,
            citation_count=1,
            last_cited_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["thread_id", "entity_id"],
            set_={
                "citation_count": ChatThreadPage.citation_count + 1,
                "last_cited_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()


async def _persist_message(
    db_factory: async_sessionmaker, thread_id, role: str, content: str
) -> None:
    async with db_factory() as session:
        session.add(ChatMessage(thread_id=thread_id, role=role, content=content))
        await session.commit()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    llm = request.app.state.llm
    embedder = request.app.state.embedder
    db_factory = request.app.state.db

    thread_id = body.thread_id
    if thread_id is not None:
        async with db_factory() as session:
            t = await session.get(ChatThread, thread_id)
            if t is None:
                raise HTTPException(status_code=404, detail="Thread not found")

    search_engine = SearchEngine(db=db_factory, embedder=embedder)
    results = await search_engine.search(body.message, limit=5)

    context_entities: list[dict] = []
    async with db_factory() as session:
        for r in results:
            entity = await session.get(Entity, r.entity_id)
            if entity:
                context_entities.append(
                    {
                        "id": str(entity.id),
                        "name": entity.canonical_name,
                        "type": entity.entity_type,
                        "page_content": (entity.page_content or "")[:3000],
                        "page_overview": entity.page_overview,
                        "description": entity.description,
                    }
                )

    context_block = (
        _format_context(context_entities) if context_entities else "(No relevant entities found)"
    )

    system = f"""You are M3, a personal knowledge assistant. You answer questions using the user's personal knowledge graph as your knowledge base.

Available entities:

{context_block}

Rules:
- Ground your answers in the entity content above. Do not make things up.
- Cite entities by wrapping their exact canonical name in double brackets: [[Entity Name]].
- If you don't have enough context to answer, say so honestly.
- Be concise and direct. No fluff."""

    if thread_id is not None:
        await _persist_message(db_factory, thread_id, "user", body.message)

    async def event_stream() -> AsyncIterator[str]:
        buffer = ""
        cited_names: set[str] = set()
        full_response = ""

        async for chunk in llm.complete_stream(
            messages=[{"role": "user", "content": body.message}],
            system=system,
            temperature=0.5,
        ):
            full_response += chunk
            buffer += chunk
            yield f"data: {json.dumps({'text': chunk})}\n\n"

            # Drain completed [[...]] mentions from the running buffer.
            while True:
                m = MENTION_RE.search(buffer)
                if m is None:
                    break
                name = m.group(1)
                buffer = buffer[m.end():]
                key = name.lower().strip()
                if key in cited_names:
                    continue
                cited_names.add(key)
                cite = await _resolve_mention(db_factory, name)
                if cite is None:
                    continue
                yield f"data: {json.dumps({'cite': cite})}\n\n"
                if thread_id is not None:
                    await _record_thread_citation(
                        db_factory, thread_id, cite["entity_id"]
                    )

        if thread_id is not None:
            await _persist_message(db_factory, thread_id, "assistant", full_response)

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
