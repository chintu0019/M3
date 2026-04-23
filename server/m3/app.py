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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from m3.api.auth import auth_middleware
from m3.api.chat import build_chat_router
from m3.api.chats import build_chats_router
from m3.api.entities_new import build_entities_router
from m3.api.ingest_http import build_ingest_router
from m3.api.items import build_items_router
from m3.api.questions import build_questions_router
from m3.api.retrieve import build_retrieve_router
from m3.api.self_doc import build_self_router
from m3.api.settings import build_settings_router

logger = logging.getLogger("m3.app")


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def build_app(*, brain_root: Path, embedder: _Embedder, llm_factory=None) -> FastAPI:
    app = FastAPI(title="M3", version="0.2.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    # Optional bearer auth for /api/v1/*. Resolves config per-request so
    # `m3 auth` CLI changes take effect without a server restart.
    app.middleware("http")(auth_middleware)
    app.state.brain_root = brain_root
    app.state.embedder = embedder
    app.state.llm_factory = llm_factory

    app.include_router(build_retrieve_router(brain_root=brain_root, embedder=embedder))
    app.include_router(build_ingest_router(brain_root=brain_root, embedder=embedder, llm_factory=llm_factory))
    app.include_router(build_self_router(brain_root=brain_root))
    app.include_router(build_entities_router(brain_root=brain_root))
    app.include_router(build_questions_router(brain_root=brain_root))
    app.include_router(build_items_router(brain_root=brain_root))
    app.include_router(build_chat_router(brain_root=brain_root, embedder=embedder, llm_factory=llm_factory))
    app.include_router(build_chats_router(brain_root=brain_root))
    app.include_router(build_settings_router())

    @app.get("/api/v1/status")
    async def status():
        return {"ok": True, "brain_root": str(brain_root)}

    # Serve the built React client (if the bundle exists). This lets `m3 start`
    # open the browser to a working SPA without any separate build step at run time.
    _client_dist = Path(__file__).resolve().parent.parent.parent / "client" / "dist"
    if _client_dist.exists():
        app.mount("/assets", StaticFiles(directory=_client_dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        async def _index():
            return FileResponse(_client_dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str):
            # Let API routes 404 normally; only fallback for non-/api paths.
            if full_path.startswith("api/"):
                return FileResponse(_client_dist / "index.html", status_code=404)
            return FileResponse(_client_dist / "index.html")

    return app


def _default_brain() -> Path:
    return Path(os.environ.get("M3_BRAIN", str(Path.home() / "brain")))


def _make_embedder():
    from m3.core.llm.embeddings import FastEmbedProvider
    return FastEmbedProvider()


def _make_llm():
    """Pick an LLM provider from config (env > config.yml > default).

    Called per-request via llm_factory, so a change to config.yml or env takes
    effect on the NEXT incoming request with no server restart needed.

    Also honors M3_LLM_PROVIDER=fake for the E2E smoke test — kept in sync with
    the CLI path in cli.py::_make_llm so `m3 start` exercises the same fake
    behavior that per-module tests do. The fake provider is env-only (never
    persisted to config.yml).
    """
    from m3.core import config as _cfg
    provider = _cfg.llm_provider().lower()
    if provider == "fake":
        from m3.cli import _FakeLLM
        return _FakeLLM()
    if provider == "ollama":
        from m3.core.llm.ollama import OllamaProvider
        return OllamaProvider(host=_cfg.ollama_host(), model=_cfg.ollama_model())
    if provider == "anthropic":
        key = _cfg.anthropic_api_key()
        if not key:
            raise RuntimeError("anthropic provider selected but no API key configured")
        from m3.core.llm.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=key, model=_cfg.anthropic_model())
    raise RuntimeError(f"unknown LLM provider: {provider!r}")


def run() -> None:
    """Entrypoint for the m3-server console script and `m3 start`."""
    brain = _default_brain()
    if not (brain / "self.md").exists():
        raise SystemExit(f"brain at {brain} is not initialized. Run `m3 init` first.")
    embedder = _make_embedder()
    app = build_app(brain_root=brain, embedder=embedder, llm_factory=_make_llm)
    host = os.environ.get("M3_HOST", "127.0.0.1")
    port = int(os.environ.get("M3_PORT", "7007"))
    logger.info("M3 server starting at http://%s:%d (brain=%s)", host, port, brain)
    uvicorn.run(app, host=host, port=port, log_level="info")
