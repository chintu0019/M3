"""HTTP surface for retrieval. Pure filesystem + sqlite — no legacy DB deps.

build_retrieve_app is for local-only (127.0.0.1) Tauri / CLI contexts. Servers
exposing retrieve over a network must use
build_retrieve_router(dependencies=[Depends(auth)]) instead so the endpoint
enforces the same auth as sibling routes on the same port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, FastAPI, Query
from pydantic import BaseModel, Field

from m3.core.retrieve import RetrievalHit, Retriever


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RetrieveHitModel(BaseModel):
    item_id: str
    score: float
    kind: str
    when_iso: str | None = None
    snippet: str
    excerpt: str
    reasons: list[str] = Field(default_factory=list)


class RetrieveResponse(BaseModel):
    hits: list[RetrieveHitModel]


def build_retrieve_router(
    *,
    brain_root: Path,
    embedder: _Embedder,
    dependencies: list | None = None,
) -> APIRouter:
    """Build the retrieve router. Pass `dependencies=[Depends(auth)]` when
    mounting into a networked app so the endpoint is protected alongside the
    rest of the surface."""
    router = APIRouter(
        prefix="/api/v1",
        tags=["retrieve"],
        dependencies=list(dependencies or []),
    )
    retriever = Retriever(brain_root=brain_root, embedder=embedder)

    @router.get("/retrieve", response_model=RetrieveResponse)
    async def retrieve(
        q: str = Query("", description="Fragment query"),
        k: int = Query(10, ge=1, le=100),
        since: str | None = Query(None, description="ISO date lower bound on when_iso"),
        until: str | None = Query(None, description="ISO date upper bound on when_iso"),
    ):
        hits = await retriever.search(q, k=k, since_iso=since, until_iso=until)
        return RetrieveResponse(hits=[_to_model(h) for h in hits])

    return router


def build_retrieve_app(*, brain_root: Path, embedder: _Embedder) -> FastAPI:
    """Build a minimal FastAPI app hosting just the retrieve router.

    Used by tests and the upcoming local-server mode. The legacy main.py app
    will continue to exist until P3 removes it; that app can also mount this
    router via `app.include_router(build_retrieve_router(...))`.
    """
    app = FastAPI(title="M3 Retrieve")
    app.include_router(build_retrieve_router(brain_root=brain_root, embedder=embedder))
    return app


def _to_model(h: RetrievalHit) -> RetrieveHitModel:
    return RetrieveHitModel(
        item_id=h.item_id, score=h.score, kind=h.kind, when_iso=h.when_iso,
        snippet=h.snippet, excerpt=h.excerpt, reasons=list(h.reasons),
    )
