"""
M3 ARQ Tasks -- background job definitions for the worker.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arq import cron
from sqlalchemy import or_, update

from m3.config import LLMProviderConfig, load_settings
from m3.core.compiler import Compiler
from m3.core.engines.loader import load_engine
from m3.core.llm import create_embedding_provider, create_llm_provider
from m3.storage.database import init_db
from m3.storage.files import FileStore
from m3.storage.models import RawItem
from m3.storage.user_settings import UserSettingsStore

STALE_PROCESSING_THRESHOLD = timedelta(minutes=10)

logger = logging.getLogger("m3.worker")


async def process_item(ctx: dict, item_id: str) -> None:
    """Process a single raw item through the compilation pipeline."""
    compiler: Compiler = ctx["compiler"]
    await compiler.process_item(uuid.UUID(item_id))


async def compile_pass(ctx: dict) -> None:
    """Process all pending items."""
    compiler: Compiler = ctx["compiler"]
    count = await compiler.run_compile_pass()
    logger.info(f"Compile pass finished: {count} items")


async def deep_compile(ctx: dict) -> None:
    """Weekly deep synthesis of the entire wiki."""
    compiler: Compiler = ctx["compiler"]
    await compiler.run_deep_compile()


async def startup(ctx: dict) -> None:
    """Initialize all dependencies for the worker process."""
    logger.info("Worker starting up...")
    settings = load_settings()

    # Merge user-configured providers (same as server lifespan)
    user_store = UserSettingsStore(Path(settings.data_dir) / "user_settings.json")
    for name, provider_data in user_store.get_providers().items():
        settings.llm.providers[name] = LLMProviderConfig(**provider_data)
    user_active = user_store.get_active_provider()
    if user_active and user_active in settings.llm.providers:
        settings.llm.default_provider = user_active

    engine, session_factory = await init_db(settings.database)
    file_store = FileStore(settings.storage)
    await file_store.ensure_bucket()

    llm = create_llm_provider(settings.llm)
    embedder = create_embedding_provider(settings.llm.embedding)
    compilation_engine = load_engine(settings.processing, llm)

    compiler = Compiler(
        db=session_factory,
        files=file_store,
        engine=compilation_engine,
        llm=llm,
        embedder=embedder,
        wiki_mode=settings.processing.wiki_mode,
    )

    ctx["compiler"] = compiler
    ctx["db_engine"] = engine
    ctx["settings"] = settings

    # Reap zombie 'processing' items from a previous worker that crashed
    # mid-job. Reset them to 'pending' so the next compile_pass (hourly cron,
    # or the immediate pass below) picks them up. Two cases caught: items with
    # no processing_started_at (older data pre-Task 10) and items whose stamp
    # is older than STALE_PROCESSING_THRESHOLD.
    cutoff = datetime.now(timezone.utc) - STALE_PROCESSING_THRESHOLD
    async with session_factory() as session:
        result = await session.execute(
            update(RawItem)
            .where(
                RawItem.status == "processing",
                or_(
                    RawItem.processing_started_at.is_(None),
                    RawItem.processing_started_at < cutoff,
                ),
            )
            .values(status="pending", processing_started_at=None, processed_at=None)
        )
        await session.commit()
        if result.rowcount:
            logger.warning(f"Recovered {result.rowcount} zombie processing items")

    # Also run an immediate compile pass so unstuck items (and any backlog
    # accumulated while the worker was down) start processing right away
    # rather than waiting up to an hour for the cron.
    await compiler.run_compile_pass()

    logger.info("Worker ready")


async def shutdown(ctx: dict) -> None:
    """Cleanup worker resources."""
    logger.info("Worker shutting down...")
    if "db_engine" in ctx:
        await ctx["db_engine"].dispose()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [process_item]
    cron_jobs = [
        cron(compile_pass, minute={0}),  # Every hour on the hour
        cron(deep_compile, weekday={6}, hour={3}, minute={0}),  # Sunday 3am
    ]
    on_startup = startup
    on_shutdown = shutdown
    # redis_settings set by run.py at runtime
