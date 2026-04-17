"""
M3 Chat API — streaming SSE chat grounded in the entity knowledge graph.
"""

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.api.deps import verify_auth
from m3.core.search import SearchEngine
from m3.schemas.api import ChatRequest
from m3.storage.models import Entity

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _format_context(entities: list[dict]) -> str:
    """Render each entity block with its type header + page_content (or overview)."""
    parts = []
    for e in entities:
        body = e.get("page_content") or e.get("page_overview") or e.get("description") or ""
        parts.append(f"### [[{e['name']}]] ({e['type']})\n{body}")
    return "\n\n---\n\n".join(parts)


async def _resolve_citations(
    db_factory: async_sessionmaker, full_text: str
) -> list[dict]:
    """Resolve [[Name]] mentions in the LLM response to entity ids.

    Matches against canonical_name (case-insensitive) or any row in ``aliases``.
    """
    mentions = re.findall(r"\[\[(.+?)\]\]", full_text)
    if not mentions:
        return []

    citations: list[dict] = []
    seen: set[str] = set()
    async with db_factory() as session:
        for name in mentions:
            key = name.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            result = await session.execute(
                select(Entity.id, Entity.canonical_name, Entity.entity_type)
                .where(
                    or_(
                        func.lower(Entity.canonical_name) == key,
                        Entity.aliases.any(name),
                    )
                )
                .limit(1)
            )
            row = result.first()
            if row:
                citations.append(
                    {
                        "entity_id": str(row[0]),
                        "name": row[1],
                        "entity_type": row[2],
                    }
                )
    return citations


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    _auth: str = Depends(verify_auth),
):
    llm = request.app.state.llm
    embedder = request.app.state.embedder
    db_factory = request.app.state.db

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

    context_block = _format_context(context_entities) if context_entities else "(No relevant entities found)"

    system = f"""You are M3, a personal knowledge assistant. You answer questions using the user's personal knowledge graph as your knowledge base.

Available entities:

{context_block}

Rules:
- Ground your answers in the entity content above. Do not make things up.
- Cite entities by wrapping their exact canonical name in double brackets: [[Entity Name]].
- If you don't have enough context to answer, say so honestly.
- Be concise and direct. No fluff."""

    async def event_stream():
        full_response = ""
        async for chunk in llm.complete_stream(
            messages=[{"role": "user", "content": body.message}],
            system=system,
            temperature=0.5,
        ):
            full_response += chunk
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        citations = await _resolve_citations(db_factory, full_response)
        if citations:
            yield f"data: {json.dumps({'citations': citations})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
