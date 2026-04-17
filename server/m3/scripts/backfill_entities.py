"""
Backfill raw_items into the entity-centric pipeline (Phase 6).

Re-runs engine.extract() + _persist_extraction() + find_for_touched() for
every raw_item that landed before Phase 2. Idempotent: skips items that
already have entity_facts linked. Commits per item so a mid-run crash
leaves the DB consistent.

Usage (inside the server container):

    # Report what would happen, no writes.
    python -m m3.scripts.backfill_entities --dry-run

    # Apply to everything with a 1s pause between items.
    python -m m3.scripts.backfill_entities --delay 1

    # Only mark existing wiki_pages as legacy (no backfill).
    python -m m3.scripts.backfill_entities --mark-legacy-only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from m3.config import LLMProviderConfig, load_settings
from m3.core.compiler import Compiler
from m3.core.engines.base import ContentType
from m3.core.engines.loader import load_engine
from m3.core.insight_engine import find_for_touched as find_insights_for_touched
from m3.core.llm import create_embedding_provider, create_llm_provider
from m3.storage.database import init_db
from m3.storage.files import FileStore
from m3.storage.models import EntityFact, RawItem, WikiPage
from m3.storage.user_settings import UserSettingsStore

logger = logging.getLogger("m3.backfill")


async def _items_to_backfill(
    db: async_sessionmaker,
) -> tuple[list, int]:
    """Return (items_needing_backfill, items_already_done_count).

    Only touches raw_items with status='done'. Items already linked to any
    entity_fact are considered already backfilled."""
    async with db() as session:
        total_stmt = select(func.count(RawItem.id)).where(RawItem.status == "done")
        total = (await session.execute(total_stmt)).scalar_one()

        # Subquery: raw_item ids that already have at least one entity_fact.
        already_done_stmt = (
            select(EntityFact.item_id)
            .distinct()
        )
        already_rows = (await session.execute(already_done_stmt)).scalars().all()
        already = set(already_rows)

        todo_stmt = (
            select(RawItem)
            .where(RawItem.status == "done")
            .order_by(RawItem.created_at.asc())
        )
        rows = (await session.execute(todo_stmt)).scalars().all()
        todo = [r for r in rows if r.id not in already]
        return todo, total - len(todo)


async def _mark_legacy_pages(db: async_sessionmaker) -> int:
    """Flag every non-index wiki_page as legacy. Returns rows affected."""
    async with db() as session:
        result = await session.execute(
            update(WikiPage)
            .where(WikiPage.page_type != "_index")
            .where(WikiPage.legacy.is_(False))
            .values(legacy=True)
        )
        await session.commit()
        return result.rowcount or 0


async def _backfill_one(compiler: Compiler, item_id) -> dict:
    """Run the entity-mode pipeline for one raw_item. Returns a stats dict.

    We reuse the full _run_entity_mode path so the insight pass fires and
    dim tables update, instead of hand-rolling a thinner version that would
    drift from process_item's shape."""
    async with compiler.db() as session:
        item = await session.get(RawItem, item_id)
        if item is None:
            return {"skipped": True, "reason": "not_found"}

        content = await compiler._extract_content(item)
        if not content:
            return {"skipped": True, "reason": "no_content"}

        content_type = (
            ContentType(item.content_type)
            if item.content_type in ContentType.__members__.values()
            else ContentType.TEXT
        )

        # Use the text path only — multimodal backfill would require per-item
        # blocks, which is fine to add later.
        try:
            extraction = await compiler.engine.extract(
                content=content, content_type=content_type, user_notes=None,
            )
        except NotImplementedError:
            return {"skipped": True, "reason": "engine_no_extract"}
        except Exception as e:
            return {"error": str(e)[:300]}

        n_facts, touched_ids = await compiler._persist_extraction(session, item, extraction)

        insight_count = 0
        if touched_ids:
            try:
                insight_count = await find_insights_for_touched(
                    session, compiler.engine, touched_ids,
                )
            except Exception:
                logger.exception("insight pass failed during backfill; continuing")

        await session.commit()
        return {
            "entities": len(extraction.entities),
            "facts": n_facts,
            "relationships": len(extraction.relationships or []),
            "insights": insight_count,
        }


async def _build_compiler(settings) -> tuple[Compiler, object]:
    """Build a Compiler with the same wiring the worker uses."""
    user_store = UserSettingsStore(Path(settings.data_dir) / "user_settings.json")
    for name, cfg in user_store.get_providers().items():
        settings.llm.providers[name] = LLMProviderConfig(**cfg)
    active = user_store.get_active_provider()
    if active and active in settings.llm.providers:
        settings.llm.default_provider = active

    engine, session_factory = await init_db(settings.database)
    files = FileStore(settings.storage)
    await files.ensure_bucket()
    llm = create_llm_provider(settings.llm)
    embedder = create_embedding_provider(settings.llm.embedding)
    comp_engine = load_engine(settings.processing, llm)

    compiler = Compiler(
        db=session_factory, files=files, engine=comp_engine,
        llm=llm, embedder=embedder,
        wiki_mode="entity",  # force entity path regardless of current default
    )
    return compiler, engine


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill raw_items into entity pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Seconds to sleep between items (throttle LLM provider)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Stop after N items")
    parser.add_argument(
        "--mark-legacy-only", action="store_true",
        help="Skip backfill; only flag existing wiki_pages as legacy",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    compiler, db_engine = await _build_compiler(settings)

    try:
        if args.mark_legacy_only:
            if args.dry_run:
                async with compiler.db() as session:
                    count = (await session.execute(
                        select(func.count(WikiPage.id))
                        .where(WikiPage.page_type != "_index")
                        .where(WikiPage.legacy.is_(False))
                    )).scalar_one()
                print(f"[dry-run] would flag {count} wiki_pages as legacy")
            else:
                n = await _mark_legacy_pages(compiler.db)
                print(f"flagged {n} wiki_pages as legacy")
            return 0

        todo, already = await _items_to_backfill(compiler.db)
        print(
            f"backfill plan: {len(todo)} items to process, "
            f"{already} already have entity_facts (skipped)"
        )
        if args.dry_run:
            return 0
        if not todo:
            print("nothing to do")
            return 0
        if args.limit:
            todo = todo[: args.limit]
            print(f"limiting to first {len(todo)} item(s)")

        totals = {"entities": 0, "facts": 0, "relationships": 0, "insights": 0, "skipped": 0, "errors": 0}
        for i, item in enumerate(todo, 1):
            result = await _backfill_one(compiler, item.id)
            if "error" in result:
                totals["errors"] += 1
                logger.warning(f"[{i}/{len(todo)}] {item.id} error: {result['error']}")
            elif result.get("skipped"):
                totals["skipped"] += 1
                logger.info(f"[{i}/{len(todo)}] {item.id} skipped ({result.get('reason')})")
            else:
                for k in ("entities", "facts", "relationships", "insights"):
                    totals[k] += result[k]
                logger.info(
                    f"[{i}/{len(todo)}] {item.id} ok "
                    f"(e={result['entities']} f={result['facts']} "
                    f"r={result['relationships']} i={result['insights']})"
                )
            if args.delay:
                await asyncio.sleep(args.delay)

        print(
            f"done: entities={totals['entities']} facts={totals['facts']} "
            f"relationships={totals['relationships']} insights={totals['insights']} "
            f"skipped={totals['skipped']} errors={totals['errors']}"
        )
        return 0 if totals["errors"] == 0 else 1
    finally:
        await db_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
