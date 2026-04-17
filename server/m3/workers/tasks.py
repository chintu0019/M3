"""
M3 ARQ Tasks — background job definitions for the worker.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arq import cron
from sqlalchemy import or_, select, update

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
    """Process a single raw item through the entity pipeline."""
    compiler: Compiler = ctx["compiler"]
    await compiler.process_item(uuid.UUID(item_id))


async def render_dirty_entities_task(ctx: dict) -> None:
    """Regenerate entity pages that accumulated new facts. Every 5 minutes."""
    from m3.core.entity_renderer import render_dirty_entities
    compiler: Compiler = ctx["compiler"]
    n = await render_dirty_entities(
        db=compiler.db,
        files=compiler.files,
        engine=compiler.engine,
        llm=compiler.llm,
        embedder=compiler.embedder,
        limit=20,
    )
    if n:
        logger.info(f"Rendered {n} dirty entities")


async def consolidate_types_task(ctx: dict) -> None:
    """Ask the engine to merge near-duplicate rows in the type dim tables
    and rewrite base rows onto the canonical survivor. Daily at 04:00 UTC."""
    from m3.core.type_consolidator import consolidate_types
    compiler: Compiler = ctx["compiler"]
    summary = await consolidate_types(db=compiler.db, engine=compiler.engine)
    if any(summary.values()):
        logger.info(f"Type consolidation applied: {summary}")


async def drain_pending_items(ctx: dict) -> int:
    """Process any raw_items still in 'pending' — catches items whose ARQ
    job was lost (worker crashed between enqueue and run). Called on startup."""
    compiler: Compiler = ctx["compiler"]
    async with compiler.db() as session:
        result = await session.execute(
            select(RawItem.id)
            .where(RawItem.status == "pending")
            .order_by(RawItem.created_at)
        )
        item_ids = [row[0] for row in result.all()]

    for item_id in item_ids:
        await compiler.process_item(item_id)
    if item_ids:
        logger.info(f"Drained {len(item_ids)} pending items on startup")
    return len(item_ids)


async def startup(ctx: dict) -> None:
    """Initialize all dependencies for the worker process."""
    logger.info("Worker starting up...")
    settings = load_settings()

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
    )

    ctx["compiler"] = compiler
    ctx["db_engine"] = engine
    ctx["settings"] = settings

    # Reap zombie 'processing' items from a previous worker that crashed
    # mid-job. Reset to 'pending' so the drain pass below picks them up.
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

    await drain_pending_items(ctx)

    logger.info("Worker ready")


async def shutdown(ctx: dict) -> None:
    """Cleanup worker resources."""
    logger.info("Worker shutting down...")
    if "db_engine" in ctx:
        await ctx["db_engine"].dispose()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [process_item, render_dirty_entities_task, consolidate_types_task]
    cron_jobs = [
        cron(render_dirty_entities_task, minute=set(range(0, 60, 5))),  # Every 5 min
        cron(consolidate_types_task, hour={4}, minute={0}),  # Daily at 04:00 UTC
    ]
    on_startup = startup
    on_shutdown = shutdown
    # redis_settings set by run.py at runtime
