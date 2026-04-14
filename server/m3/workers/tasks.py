"""
M3 ARQ Tasks -- background job definitions for the worker.
"""

import logging
import uuid

from arq import cron

from m3.config import load_settings
from m3.core.compiler import Compiler
from m3.core.engines.loader import load_engine
from m3.core.llm import create_embedding_provider, create_llm_provider
from m3.storage.database import init_db
from m3.storage.files import FileStore

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
