"""Legacy M3 entrypoint — retained for reference only. Replaced by m3.app:run in P3a."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from m3.api.canvas import router as canvas_router
from m3.api.chat import router as chat_router
from m3.api.entities import router as entities_router
from m3.api.entity_links import router as entity_links_router
from m3.api.ingest import router as ingest_router
from m3.api.insights import router as insights_router
from m3.api.library import router as library_router
from m3.api.settings import router as settings_router
from m3.api.threads import router as threads_router
from m3.config import load_settings
from m3.core.engines.loader import load_engine
from m3.core.llm import create_embedding_provider, create_llm_provider
from m3.config import LLMProviderConfig
from m3.storage.cache import Cache
from m3.storage.database import init_db
from m3.storage.files import FileStore
from m3.storage.user_settings import UserSettingsStore

logger = logging.getLogger("m3")


async def run_migrations(engine) -> None:
    """Run Alembic migrations using the existing async engine."""
    from alembic.config import Config as AlembicConfig
    from alembic import command

    def do_upgrade(connection):
        cfg = AlembicConfig("alembic.ini")
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(do_upgrade)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()

    # Init database
    engine, session_factory = await init_db(settings.database)
    app.state.db = session_factory
    app.state.db_engine = engine

    # Run database migrations
    logger.info("Running database migrations...")
    await run_migrations(engine)

    # Init file storage
    file_store = FileStore(settings.storage)
    await file_store.ensure_bucket()
    app.state.files = file_store

    # Init cache
    cache = Cache(settings.redis.url)
    app.state.cache = cache

    # Init ARQ pool for enqueuing jobs
    redis_url = settings.redis.url
    if redis_url.startswith("redis://"):
        parts = redis_url.replace("redis://", "").split(":")
        host = parts[0]
        port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
        arq_redis = RedisSettings(host=host, port=port)
    else:
        arq_redis = RedisSettings()
    app.state.arq_pool = await create_pool(arq_redis)

    # Init user settings store (persists UI-configured providers)
    user_store = UserSettingsStore(Path(settings.data_dir) / "user_settings.json")
    app.state.user_store = user_store

    # Merge user-configured providers into settings (before creating LLM)
    for name, provider_data in user_store.get_providers().items():
        settings.llm.providers[name] = LLMProviderConfig(**provider_data)
    user_active = user_store.get_active_provider()
    if user_active and user_active in settings.llm.providers:
        settings.llm.default_provider = user_active

    # Store settings
    app.state.settings = settings

    # Init LLM + embedding providers
    llm = create_llm_provider(settings.llm)
    embedder = create_embedding_provider(settings.llm.embedding)
    app.state.llm = llm
    app.state.embedder = embedder

    # Init compilation engine
    app.state.engine = load_engine(settings.processing, llm)

    # Start Telegram bot if enabled
    telegram_bot = None
    if settings.capture.telegram.enabled and settings.capture.telegram.bot_token:
        from m3.capture.telegram import TelegramCapture
        from m3.core.search import SearchEngine

        telegram_bot = TelegramCapture(settings.capture.telegram.bot_token)
        telegram_bot.db = session_factory
        telegram_bot.files = file_store
        telegram_bot.arq_pool = app.state.arq_pool
        telegram_bot.search_engine = SearchEngine(db=session_factory, embedder=embedder)
        telegram_bot.llm = llm
        await telegram_bot.start()
        logger.info("Telegram bot started")

    logger.info("M3 server started")
    yield

    # Cleanup
    if telegram_bot:
        await telegram_bot.stop()
    await engine.dispose()
    await cache.close()
    await app.state.arq_pool.close()
    logger.info("M3 server stopped")


app = FastAPI(
    title="M3",
    description="Personal Knowledge Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(ingest_router)
app.include_router(chat_router)
app.include_router(settings_router)
app.include_router(library_router)
app.include_router(entities_router)
app.include_router(entity_links_router)
app.include_router(insights_router)
app.include_router(canvas_router)
app.include_router(threads_router)


@app.get("/api/v1/status")
async def status():
    return {"status": "ok", "version": "0.1.0"}


# Serve the React client -- must come after all API routes
STATIC_DIR = Path("/app/static")
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve static files or fall back to index.html for SPA routing."""
        file_path = STATIC_DIR / path
        if path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")


def run():
    """Entry point for m3-server command."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    uvicorn.run("m3.main:app", host="0.0.0.0", port=8000, reload=False)
