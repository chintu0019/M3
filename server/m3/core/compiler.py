"""
M3 Compiler -- the processing pipeline orchestrator.

Takes raw items through: extract -> classify -> find related -> compile -> write wiki -> update links.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from m3.core.engines.base import (
    AudioBlock,
    CompilationEngine,
    ContentBlock,
    ContentType,
    EntityMention,
    ExtractedFact,
    ExtractionResult,
    ImageBlock,
    ProposedRelationship,
    TextBlock,
)
from m3.core.entity_resolver import resolve as resolve_entity
from m3.core.insight_engine import find_for_touched as find_insights_for_touched
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
from m3.storage.models import (
    Changelog,
    Entity,
    EntityFact,
    EntityFactLink,
    EntityLink,
    EntityTypeVocab,
    FactRoleVocab,
    FactTypeVocab,
    ItemNote,
    RawItem,
    WikiLink,
    WikiPage,
    WikiSchema,
)

logger = logging.getLogger("m3.compiler")


class Compiler:
    def __init__(
        self,
        db: async_sessionmaker,
        files: FileStore,
        engine: CompilationEngine,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        wiki_mode: str = "document",
    ):
        self.db = db
        self.files = files
        self.engine = engine
        self.llm = llm
        self.embedder = embedder
        self.wiki_mode = wiki_mode

    async def process_item(self, item_id: uuid.UUID) -> None:
        """Full processing pipeline for a single raw item."""
        async with self.db() as session:
            try:
                item = await session.get(RawItem, item_id)
                if not item:
                    # Belt-and-braces for enqueue-before-commit races. All
                    # known producers now commit before enqueueing, but a
                    # replication lag or a caller we missed shouldn't lose
                    # the item. One short retry clears any real race.
                    await asyncio.sleep(0.5)
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

                # 1. Extract content (text form, always) and multimodal blocks
                content = await self._extract_content(item)
                if not content:
                    item.status = "error"
                    item.error_message = "No content could be extracted"
                    await session.commit()
                    return

                if item.content_text != content:
                    item.content_text = content

                content_type = (
                    ContentType(item.content_type)
                    if item.content_type in ContentType.__members__.values()
                    else ContentType.TEXT
                )

                # Build multimodal blocks for engines that can consume them.
                content_blocks = await self._build_content_blocks(item, content)

                mode = (self.wiki_mode or "document").lower()
                if mode not in ("document", "entity", "both"):
                    logger.warning(f"Unknown wiki_mode={mode!r}; falling back to 'document'")
                    mode = "document"

                changelog_entries: list[str] = []

                if mode in ("document", "both"):
                    try:
                        entry = await self._run_document_mode(
                            session, item, content, content_type, user_notes,
                        )
                        if entry:
                            changelog_entries.append(entry)
                    except Exception:
                        if mode == "both":
                            logger.exception("document-mode failed in both mode; continuing")
                        else:
                            raise

                if mode in ("entity", "both"):
                    try:
                        entry = await self._run_entity_mode(
                            session, item, content, content_blocks, content_type, user_notes,
                        )
                        if entry:
                            changelog_entries.append(entry)
                    except Exception:
                        if mode == "both":
                            logger.exception("entity-mode failed in both mode; continuing")
                        else:
                            raise

                for entry in changelog_entries:
                    session.add(Changelog(action="compiled", description=entry))

                # Mark done
                item.status = "done"
                item.processed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info(f"Processed item {item_id} in wiki_mode={mode}")

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

    # --- Mode helpers ---

    async def _run_document_mode(
        self,
        session: AsyncSession,
        item: RawItem,
        content: str,
        content_type: ContentType,
        user_notes: str | None,
    ) -> str:
        """Legacy per-item wiki-page compilation path."""
        wiki_index = await self._get_wiki_index(session)
        wiki_schema = await self._get_wiki_schema(session)
        existing_tags = await self._get_existing_tags(session)
        existing_projects = await self._get_existing_projects(session)

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
        related_pages = await self._find_related_pages(session, content)
        compile_result = await self.engine.compile(
            classified_item=classification,
            original_content=content,
            related_pages=related_pages,
            wiki_schema=wiki_schema,
            user_notes=user_notes,
        )
        for pu in compile_result.pages:
            await self._write_page(session, pu, item.id)
        for lu in compile_result.links:
            await self._upsert_link(session, lu)
        await self._update_wiki_index(session)
        if compile_result.schema_updates:
            session.add(WikiSchema(content=compile_result.schema_updates))
        return compile_result.changelog_entry or "Content compiled"

    async def _run_entity_mode(
        self,
        session: AsyncSession,
        item: RawItem,
        content: str,
        content_blocks: list[ContentBlock],
        content_type: ContentType,
        user_notes: str | None,
    ) -> str:
        """Entity extraction path: facts into entity pages, not summary pages."""
        capabilities = getattr(self.engine, "capabilities", None)
        wants_multimodal = bool(capabilities and capabilities.multimodal) and any(
            isinstance(b, (ImageBlock, AudioBlock)) for b in content_blocks
        )
        extract_input: str | list[ContentBlock] = (
            content_blocks if wants_multimodal else content
        )
        try:
            extraction = await self.engine.extract(
                content=extract_input, content_type=content_type, user_notes=user_notes,
            )
        except NotImplementedError:
            logger.warning("Engine does not support extract(); skipping entity mode")
            return ""
        n, touched_ids = await self._persist_extraction(session, item, extraction)
        rel_count = len(extraction.relationships or [])

        # Insight pass — best-effort. Failure never blocks ingest.
        insight_count = 0
        if touched_ids:
            try:
                insight_count = await find_insights_for_touched(
                    session, self.engine, touched_ids,
                )
            except Exception:
                logger.exception("find_insights raised; ingest continues")

        summary = (
            f"Extracted {len(extraction.entities)} entities, {n} facts, "
            f"{rel_count} relationships"
        )
        if insight_count:
            summary += f", {insight_count} insights"
        return summary

    async def _build_content_blocks(
        self, item: RawItem, text_content: str,
    ) -> list[ContentBlock]:
        """Produce the multimodal ContentBlock list for this item when the
        underlying LLM is multimodal. For plain-text items we return the text
        as a single TextBlock so the engine has a consistent input shape."""
        blocks: list[ContentBlock] = []

        # Image / audio get raw bytes if the LLM is vision/audio-capable.
        if item.content_type == "image" and item.file_path and self.llm.supports_vision:
            try:
                image_bytes = await self.files.download(item.file_path)
                mime = _guess_image_mime(item.file_path)
                blocks.append(ImageBlock(image_bytes=image_bytes, media_type=mime))
            except Exception as e:
                logger.warning(f"Failed to load image block: {e}")

        if item.content_type in ("audio", "voice") and item.file_path and self.llm.supports_audio:
            try:
                audio_bytes = await self.files.download(item.file_path)
                mime = _guess_audio_mime(item.file_path)
                blocks.append(AudioBlock(audio_bytes=audio_bytes, media_type=mime))
            except Exception as e:
                logger.warning(f"Failed to load audio block: {e}")

        if text_content:
            blocks.append(TextBlock(text=text_content))

        return blocks

    # --- Entity persistence ---

    async def _persist_extraction(
        self,
        session: AsyncSession,
        item: RawItem,
        extraction: ExtractionResult,
    ) -> tuple[int, list[uuid.UUID]]:
        """Write entities, facts, fact-links, and entity_links for one item.
        Returns (facts_persisted, touched_entity_ids)."""
        if not extraction.entities and not extraction.facts:
            return 0, []

        # 1) Resolve every mention up front so facts can reuse the cache.
        resolved: dict[tuple[str, str], Entity] = {}
        for mention in extraction.entities:
            outcome = await resolve_entity(session, self.embedder, self.llm, mention)
            key = (mention.canonical_name.lower(), mention.entity_type.lower())
            resolved[key] = outcome.entity
            for alias in mention.aliases or []:
                resolved.setdefault((alias.lower(), mention.entity_type.lower()), outcome.entity)
            await self._bump_type_vocab(session, EntityTypeVocab, outcome.entity.entity_type)

        # 2) Facts + fact-links.
        pair_counts: dict[frozenset, int] = {}
        persisted_facts = 0
        for ef in extraction.facts:
            fact_time = _parse_iso_datetime(ef.fact_time_iso)

            fact = EntityFact(
                content=ef.content,
                fact_type=ef.fact_type,
                fact_time=fact_time,
                source_quote=ef.source_quote,
                item_id=item.id,
                confidence=ef.confidence,
            )
            session.add(fact)
            await session.flush()
            await self._bump_type_vocab(session, FactTypeVocab, ef.fact_type)

            # Two passes: (1) resolve every ref and pick the strongest
            # role when the LLM emits the same entity twice in one fact;
            # (2) emit one fact-link row per unique entity. The PK on
            # entity_fact_links is (fact_id, entity_id), so duplicate
            # (entity, fact) pairs with different roles would otherwise
            # violate it.
            role_rank = {
                "subject": 3, "attributed_to": 2,
                "location": 1, "time": 1, "mentioned": 0,
            }
            best_role: dict[uuid.UUID, str] = {}
            ordered_ids: list[uuid.UUID] = []

            for ref in ef.entity_refs:
                rname = (ref.get("name") or "").strip()
                rtype = (ref.get("type") or "topic").strip().lower()
                role = (ref.get("role") or "subject").strip().lower()
                if not rname:
                    continue
                key = (rname.lower(), rtype)
                ent = resolved.get(key)
                if ent is None:
                    outcome = await resolve_entity(
                        session, self.embedder, self.llm,
                        EntityMention(
                            canonical_name=rname, entity_type=rtype,
                            aliases=[], description=None,
                            context=ef.source_quote or ef.content,
                        ),
                    )
                    ent = outcome.entity
                    resolved[key] = ent
                    await self._bump_type_vocab(session, EntityTypeVocab, ent.entity_type)

                prev = best_role.get(ent.id)
                if prev is None:
                    best_role[ent.id] = role
                    ordered_ids.append(ent.id)
                elif role_rank.get(role, 0) > role_rank.get(prev, 0):
                    best_role[ent.id] = role

            linked_entity_ids: list[uuid.UUID] = []
            for eid in ordered_ids:
                role = best_role[eid]
                # Find the Entity row we already resolved so we can mark dirty.
                ent = next(e for e in resolved.values() if e.id == eid)
                session.add(EntityFactLink(fact_id=fact.id, entity_id=eid, role=role))
                await self._bump_type_vocab(session, FactRoleVocab, role)
                ent.page_dirty = True
                ent.facts_since_render = (ent.facts_since_render or 0) + 1
                linked_entity_ids.append(eid)

            persisted_facts += 1

            # Co-occurrence pairs (fallback graph signal).
            uniq = list(dict.fromkeys(linked_entity_ids))
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    pair = frozenset({uniq[i], uniq[j]})
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1

        await session.flush()

        # 3) Upsert co-occurrence entity_links.
        for pair, count in pair_counts.items():
            a, b = sorted(pair, key=lambda x: str(x))
            await self._upsert_entity_link(session, a, b, "related", count)

        # 4) Engine-proposed semantic relationships. Resolve names against the
        # per-item cache; relationships referencing unknown entities are skipped
        # rather than creating silent new rows.
        for rel in extraction.relationships or []:
            src = resolved.get((rel.source_name.lower(), rel.source_type.lower()))
            tgt = resolved.get((rel.target_name.lower(), rel.target_type.lower()))
            if src is None or tgt is None or src.id == tgt.id:
                continue
            # Canonical ordering for undirected link types; directed types keep
            # the engine's direction.
            undirected = rel.link_type in {"related", "contradicts"}
            if undirected:
                a, b = sorted([src.id, tgt.id], key=lambda x: str(x))
            else:
                a, b = src.id, tgt.id
            await self._upsert_entity_link(session, a, b, rel.link_type, rel.weight)

        await session.flush()
        touched_ids = list({e.id for e in resolved.values()})
        return persisted_facts, touched_ids

    async def _upsert_entity_link(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        link_type: str,
        weight_delta: int,
    ) -> None:
        result = await session.execute(
            select(EntityLink).where(
                EntityLink.source_entity_id == source_id,
                EntityLink.target_entity_id == target_id,
                EntityLink.link_type == link_type,
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            session.add(EntityLink(
                source_entity_id=source_id,
                target_entity_id=target_id,
                link_type=link_type,
                weight=weight_delta,
            ))
        else:
            link.weight = (link.weight or 0) + weight_delta

    async def _bump_type_vocab(self, session: AsyncSession, model, name: str) -> None:
        """Increment usage_count for a type value; insert if missing."""
        if not name:
            return
        stmt = pg_insert(model.__table__).values(name=name, usage_count=1).on_conflict_do_update(
            index_elements=["name"],
            set_={"usage_count": model.__table__.c.usage_count + 1},
        )
        await session.execute(stmt)

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


# --- Module-level helpers ---


_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_AUDIO_MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
}


def _guess_image_mime(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _IMAGE_MIME_BY_EXT.get("." + ext, "image/jpeg")


def _guess_audio_mime(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _AUDIO_MIME_BY_EXT.get("." + ext, "audio/mp4")


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
