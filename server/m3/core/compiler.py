"""
M3 Compiler -- the processing pipeline orchestrator.

Takes raw items through: extract -> classify -> find related -> compile -> write wiki -> update links.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from m3.core.engines.base import CompilationEngine, ContentType
from m3.core.extractors import (
    extract_by_filename,
    extract_docx,
    extract_epub,
    extract_html,
    extract_pdf,
    extract_pptx,
    extract_url,
    extract_xlsx,
)
from m3.core.llm import EmbeddingProvider, LLMProvider, make_content_blocks
from m3.storage.files import FileStore
from m3.storage.models import Changelog, ItemNote, RawItem, WikiLink, WikiPage, WikiSchema

logger = logging.getLogger("m3.compiler")


class Compiler:
    def __init__(
        self,
        db: async_sessionmaker,
        files: FileStore,
        engine: CompilationEngine,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
    ):
        self.db = db
        self.files = files
        self.engine = engine
        self.llm = llm
        self.embedder = embedder

    async def process_item(self, item_id: uuid.UUID) -> None:
        """Full processing pipeline for a single raw item."""
        async with self.db() as session:
            try:
                item = await session.get(RawItem, item_id)
                if not item:
                    logger.error(f"Item {item_id} not found")
                    return

                item.status = "processing"
                item.processing_started_at = datetime.now(timezone.utc)
                await session.commit()

                # Load notes for this item (user corrections / additional context)
                notes_result = await session.execute(
                    select(ItemNote).where(ItemNote.item_id == item_id).order_by(ItemNote.created_at)
                )
                notes = notes_result.scalars().all()
                user_notes = None
                if notes:
                    user_notes = "\n\n---\n\n".join(
                        f"Note (added {n.created_at.isoformat()}):\n{n.content}" for n in notes
                    )

                # 1. Extract content
                content = await self._extract_content(item)
                if not content:
                    item.status = "error"
                    item.error_message = "No content could be extracted"
                    await session.commit()
                    return

                # Store extracted text back on item if it was derived
                if item.content_text != content:
                    item.content_text = content

                # 2. Get wiki context
                wiki_index = await self._get_wiki_index(session)
                wiki_schema = await self._get_wiki_schema(session)
                existing_tags = await self._get_existing_tags(session)
                existing_projects = await self._get_existing_projects(session)

                # 3. Classify
                content_type = ContentType(item.content_type) if item.content_type in ContentType.__members__.values() else ContentType.TEXT
                classification = await self.engine.classify(
                    content=content,
                    content_type=content_type,
                    wiki_index=wiki_index,
                    wiki_schema=wiki_schema,
                    existing_tags=existing_tags,
                    existing_projects=existing_projects,
                    user_tags=item.user_tags,
                    user_project=item.user_project,
                    user_notes=user_notes,
                )

                # 4. Find related pages
                related_pages = await self._find_related_pages(session, content)

                # 5. Compile
                compile_result = await self.engine.compile(
                    classified_item=classification,
                    original_content=content,
                    related_pages=related_pages,
                    wiki_schema=wiki_schema,
                    user_notes=user_notes,
                )

                # 6. Write wiki pages
                for page_update in compile_result.pages:
                    await self._write_page(session, page_update, item.id)

                # 7. Update links
                for link_update in compile_result.links:
                    await self._upsert_link(session, link_update)

                # 8. Update wiki index (deterministic)
                await self._update_wiki_index(session)

                # 9. Update schema if needed
                if compile_result.schema_updates:
                    session.add(WikiSchema(content=compile_result.schema_updates))

                # 10. Log changelog
                session.add(Changelog(
                    action="compiled",
                    description=compile_result.changelog_entry,
                ))

                # 11. Mark done
                item.status = "done"
                item.processed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info(f"Processed item {item_id}")

            except Exception as e:
                await session.rollback()
                # Re-fetch item in new transaction to update status
                async with self.db() as err_session:
                    err_item = await err_session.get(RawItem, item_id)
                    if err_item:
                        err_item.status = "error"
                        err_item.error_message = str(e)[:1000]
                        await err_session.commit()
                logger.exception(f"Failed to process item {item_id}")

    async def run_compile_pass(self) -> int:
        """Process all pending items. Returns count processed."""
        async with self.db() as session:
            result = await session.execute(
                select(RawItem.id)
                .where(RawItem.status == "pending")
                .order_by(RawItem.created_at)
            )
            item_ids = [row[0] for row in result.all()]

        count = 0
        for item_id in item_ids:
            await self.process_item(item_id)
            count += 1

        logger.info(f"Compile pass complete: {count} items processed")
        return count

    async def run_deep_compile(self) -> None:
        """Weekly deep synthesis -- cross-reference entire wiki."""
        async with self.db() as session:
            wiki_index = await self._get_wiki_index(session)
            wiki_schema = await self._get_wiki_schema(session)

            # Get recent changelog
            result = await session.execute(
                select(Changelog.description)
                .order_by(Changelog.created_at.desc())
                .limit(50)
            )
            recent_changes = [row[0] for row in result.all() if row[0]]

            # Get all page summaries
            result = await session.execute(
                select(WikiPage.id, WikiPage.title, WikiPage.category, WikiPage.content)
                .where(WikiPage.page_type != "_index")
            )
            all_summaries = [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "category": row[2],
                    "summary": row[3][:200] if row[3] else "",
                }
                for row in result.all()
            ]

        if not all_summaries:
            logger.info("No pages to synthesize")
            return

        # Run synthesis
        synthesis = await self.engine.synthesize(
            wiki_index=wiki_index,
            wiki_schema=wiki_schema,
            recent_changes=recent_changes,
            all_page_summaries=all_summaries,
        )

        # Apply results
        async with self.db() as session:
            for link_update in synthesis.new_links:
                await self._upsert_link(session, link_update)

            if synthesis.schema_updates:
                session.add(WikiSchema(content=synthesis.schema_updates))

            for entry in synthesis.changelog_entries:
                session.add(Changelog(action="synthesized", description=entry))

            await session.commit()

        # Update index
        async with self.db() as session:
            await self._update_wiki_index(session)
            await session.commit()

        logger.info(
            f"Deep compile complete: {len(synthesis.new_links)} new links, "
            f"{len(synthesis.insights)} insights"
        )

    # --- Private helpers ---

    async def _extract_content(self, item: RawItem) -> str:
        """Extract text content from a raw item based on its type."""
        if item.content_type == "url" and item.content_text:
            return await extract_url(item.content_text)

        if item.content_type == "pdf" and item.file_path:
            pdf_bytes = await self.files.download(item.file_path)
            return await extract_pdf(pdf_bytes)

        if item.content_type == "docx" and item.file_path:
            docx_bytes = await self.files.download(item.file_path)
            return await extract_docx(docx_bytes)

        if item.content_type == "xlsx" and item.file_path:
            xlsx_bytes = await self.files.download(item.file_path)
            return await extract_xlsx(xlsx_bytes)

        if item.content_type == "pptx" and item.file_path:
            pptx_bytes = await self.files.download(item.file_path)
            return await extract_pptx(pptx_bytes)

        if item.content_type == "epub" and item.file_path:
            epub_bytes = await self.files.download(item.file_path)
            return await extract_epub(epub_bytes)

        if item.content_type == "html" and item.file_path:
            html_bytes = await self.files.download(item.file_path)
            return await extract_html(html_bytes)

        if item.content_type == "file" and item.file_path:
            # Generic file -- dispatch by extension
            file_bytes = await self.files.download(item.file_path)
            filename = item.file_path.rsplit("/", 1)[-1]
            extracted = await extract_by_filename(file_bytes, filename)
            if extracted:
                return extracted
            # Fallback to any user-provided text
            return item.content_text or ""

        if item.content_type == "image" and item.file_path:
            image_bytes = await self.files.download(item.file_path)
            mime = "image/jpeg"  # Default; could be improved with actual detection
            blocks = make_content_blocks(
                text="Describe this image in detail. Extract all visible text.",
                image_bytes=image_bytes,
                media_type=mime,
            )
            return await self.llm.complete(
                messages=[{"role": "user", "content": blocks}],
                max_tokens=2000,
            )

        if item.content_type in ("audio", "voice") and item.file_path:
            audio_bytes = await self.files.download(item.file_path)
            mime = "audio/mp4"  # Default
            blocks = make_content_blocks(
                text="Transcribe this audio. Include a brief summary.",
                audio_bytes=audio_bytes,
                media_type=mime,
            )
            return await self.llm.complete(
                messages=[{"role": "user", "content": blocks}],
                max_tokens=4000,
            )

        # Default: use content_text directly
        return item.content_text or ""

    async def _get_wiki_index(self, session: AsyncSession) -> str:
        result = await session.execute(
            select(WikiPage.content).where(WikiPage.page_type == "_index")
        )
        row = result.first()
        return row[0] if row else ""

    async def _get_wiki_schema(self, session: AsyncSession) -> str:
        result = await session.execute(
            select(WikiSchema.content).order_by(WikiSchema.id.desc()).limit(1)
        )
        row = result.first()
        return row[0] if row else ""

    async def _get_existing_tags(self, session: AsyncSession) -> list[str]:
        result = await session.execute(
            text("SELECT DISTINCT unnest(tags) AS tag FROM wiki_pages ORDER BY tag")
        )
        return [row[0] for row in result.all()]

    async def _get_existing_projects(self, session: AsyncSession) -> list[str]:
        result = await session.execute(
            select(WikiPage.category).where(WikiPage.category.isnot(None)).distinct()
        )
        return [row[0] for row in result.all()]

    async def _find_related_pages(
        self, session: AsyncSession, content: str, limit: int = 5
    ) -> list[dict]:
        """Find related pages via vector similarity + FTS, merged with RRF."""
        # Embed the content
        try:
            embeddings = await self.embedder.embed([content[:2000]])
            query_embedding = embeddings[0]
        except Exception:
            logger.warning("Embedding failed, falling back to FTS only")
            query_embedding = None

        vector_results = []
        if query_embedding:
            result = await session.execute(
                select(WikiPage.id, WikiPage.title, WikiPage.content, WikiPage.category)
                .where(WikiPage.embedding.isnot(None))
                .where(WikiPage.page_type != "_index")
                .order_by(WikiPage.embedding.cosine_distance(query_embedding))
                .limit(limit * 2)
            )
            vector_results = list(result.all())

        # FTS search
        search_terms = " ".join(content.split()[:20])
        fts_results = []
        if search_terms.strip():
            result = await session.execute(
                select(WikiPage.id, WikiPage.title, WikiPage.content, WikiPage.category)
                .where(WikiPage.page_type != "_index")
                .where(
                    func.to_tsvector("english", func.coalesce(WikiPage.title, "") + " " + func.coalesce(WikiPage.content, ""))
                    .match(search_terms)
                )
                .limit(limit * 2)
            )
            fts_results = list(result.all())

        # Merge via RRF
        scores: dict[uuid.UUID, float] = {}
        page_data: dict[uuid.UUID, dict] = {}
        k = 60

        for rank, row in enumerate(vector_results):
            page_id = row[0]
            scores[page_id] = scores.get(page_id, 0) + 1 / (k + rank)
            page_data[page_id] = {
                "id": str(page_id),
                "title": row[1],
                "content": row[2],
                "category": row[3],
            }

        for rank, row in enumerate(fts_results):
            page_id = row[0]
            scores[page_id] = scores.get(page_id, 0) + 1 / (k + rank)
            if page_id not in page_data:
                page_data[page_id] = {
                    "id": str(page_id),
                    "title": row[1],
                    "content": row[2],
                    "category": row[3],
                }

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:limit]
        return [page_data[pid] for pid in sorted_ids]

    async def _write_page(
        self, session: AsyncSession, page_update, source_item_id: uuid.UUID
    ) -> WikiPage:
        """Create or update a wiki page from a PageUpdate."""
        # Embed the page content
        try:
            embeddings = await self.embedder.embed([f"{page_update.title}\n{page_update.content[:2000]}"])
            embedding = embeddings[0]
        except Exception:
            logger.warning(f"Failed to embed page '{page_update.title}'")
            embedding = None

        if page_update.page_id:
            # Update existing page
            try:
                existing_id = uuid.UUID(page_update.page_id)
            except ValueError:
                existing_id = None

            if existing_id:
                page = await session.get(WikiPage, existing_id)
                if page:
                    page.content = page_update.content
                    page.category = page_update.category
                    page.tags = page_update.tags
                    page.confidence = page_update.confidence
                    page.embedding = embedding
                    if source_item_id not in (page.source_items or []):
                        page.source_items = (page.source_items or []) + [source_item_id]
                    return page

        # Create new page
        page = WikiPage(
            title=page_update.title,
            content=page_update.content,
            category=page_update.category,
            page_type=page_update.page_type,
            tags=page_update.tags,
            confidence=page_update.confidence,
            embedding=embedding,
            source_items=[source_item_id],
        )
        session.add(page)
        await session.flush()
        return page

    async def _upsert_link(self, session: AsyncSession, link_update) -> None:
        """Create a wiki link, resolving page titles to IDs."""
        source = await session.execute(
            select(WikiPage.id).where(WikiPage.title == link_update.source_title).limit(1)
        )
        target = await session.execute(
            select(WikiPage.id).where(WikiPage.title == link_update.target_title).limit(1)
        )

        source_row = source.first()
        target_row = target.first()

        if not source_row or not target_row:
            return

        stmt = pg_insert(WikiLink).values(
            source_page_id=source_row[0],
            target_page_id=target_row[0],
            link_type=link_update.link_type,
            weight=link_update.weight,
        ).on_conflict_do_update(
            constraint="wiki_links_source_page_id_target_page_id_link_type_key",
            set_={"weight": link_update.weight},
        )
        await session.execute(stmt)

    async def _update_wiki_index(self, session: AsyncSession) -> None:
        """Regenerate the wiki index page deterministically (no LLM call)."""
        result = await session.execute(
            select(WikiPage.title, WikiPage.category, WikiPage.page_type)
            .where(WikiPage.page_type != "_index")
            .order_by(WikiPage.category, WikiPage.title)
        )
        pages = result.all()

        if not pages:
            return

        # Group by category
        categories: dict[str, list[str]] = {}
        for title, category, _page_type in pages:
            cat = category or "Uncategorized"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(title)

        # Build index markdown
        lines = ["# M3 Wiki Index\n"]
        for cat in sorted(categories.keys()):
            lines.append(f"## {cat}\n")
            for title in sorted(categories[cat]):
                lines.append(f"- {title}")
            lines.append("")

        index_content = "\n".join(lines)

        # Upsert index page
        existing = await session.execute(
            select(WikiPage).where(WikiPage.page_type == "_index")
        )
        index_page = existing.scalar_one_or_none()

        if index_page:
            index_page.content = index_content
        else:
            session.add(WikiPage(
                title="Wiki Index",
                content=index_content,
                page_type="_index",
                tags=[],
                confidence=1.0,
            ))

        await session.flush()
