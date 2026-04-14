"""
M3 Chat API -- streaming SSE chat grounded in wiki content.
"""

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from m3.api.deps import verify_auth
from m3.core.search import SearchEngine
from m3.schemas.api import ChatRequest
from m3.storage.models import WikiPage

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _format_context(pages: list[dict]) -> str:
    """Format wiki pages into context for the LLM."""
    parts = []
    for p in pages:
        parts.append(f"### [[{p['title']}]]\n{p['content']}")
    return "\n\n---\n\n".join(parts)


async def _resolve_citations(
    db_factory, full_text: str
) -> list[dict]:
    """Find [[Page Title]] citations in the response and resolve to page IDs."""
    pattern = re.findall(r"\[\[(.+?)\]\]", full_text)
    if not pattern:
        return []

    citations = []
    seen = set()
    async with db_factory() as session:
        for title in pattern:
            if title in seen:
                continue
            seen.add(title)
            result = await session.execute(
                select(WikiPage.id, WikiPage.title)
                .where(WikiPage.title.ilike(f"%{title}%"))
                .limit(1)
            )
            row = result.first()
            if row:
                citations.append({"page_id": str(row[0]), "title": row[1]})

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

    # Search wiki for relevant context
    search_engine = SearchEngine(db=db_factory, embedder=embedder)
    results = await search_engine.search(body.message, limit=5)

    # Fetch full page content for top results
    context_pages = []
    async with db_factory() as session:
        for r in results:
            page = await session.get(WikiPage, r.page_id)
            if page:
                context_pages.append({
                    "id": str(page.id),
                    "title": page.title,
                    "content": page.content[:3000],
                })

    system = f"""You are M3, a personal knowledge assistant. You answer questions using the user's personal wiki as your knowledge base.

Available context from the wiki:

{_format_context(context_pages) if context_pages else "(No relevant wiki pages found)"}

Rules:
- Ground your answers in the wiki content above. Do not make things up.
- Cite relevant wiki pages by wrapping the page title in double brackets: [[Page Title]]
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

        # Resolve citations from the full response
        citations = await _resolve_citations(db_factory, full_response)
        if citations:
            yield f"data: {json.dumps({'citations': citations})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
