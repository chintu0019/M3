"""M3 local FastAPI app. Brain-backed, no Postgres/Redis/MinIO.

Build via `build_app(brain_root, embedder)` (for tests) or `run()` (entrypoint).
The CLI `m3 start` invokes `run`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from m3.api.retrieve import build_retrieve_router

logger = logging.getLogger("m3.app")


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def build_app(*, brain_root: Path, embedder: _Embedder) -> FastAPI:
    app = FastAPI(title="M3", version="0.2.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.state.brain_root = brain_root
    app.state.embedder = embedder

    app.include_router(build_retrieve_router(brain_root=brain_root, embedder=embedder))

    @app.get("/api/v1/status")
    async def status():
        return {"ok": True, "brain_root": str(brain_root)}

    return app


def _default_brain() -> Path:
    return Path(os.environ.get("M3_BRAIN", str(Path.home() / "brain")))


def _make_embedder():
    from m3.core.llm.embeddings import FastembedEmbeddingProvider
    return FastembedEmbeddingProvider()


def run() -> None:
    """Entrypoint for the m3-server console script and `m3 start`."""
    brain = _default_brain()
    if not (brain / "self.md").exists():
        raise SystemExit(f"brain at {brain} is not initialized. Run `m3 init` first.")
    embedder = _make_embedder()
    app = build_app(brain_root=brain, embedder=embedder)
    host = os.environ.get("M3_HOST", "127.0.0.1")
    port = int(os.environ.get("M3_PORT", "7007"))
    logger.info("M3 server starting at http://%s:%d (brain=%s)", host, port, brain)
    uvicorn.run(app, host=host, port=port, log_level="info")
