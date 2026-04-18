"""
M3 Compiler — the processing pipeline orchestrator.

Takes raw items through: content extraction -> engine.extract() -> entity
resolution -> persist facts + fact-links + entity-links -> find_insights.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from m3.core.engines.base import (
    AudioBlock,
    CompilationEngine,
    ContentBlock,
    ContentType,
    EntityMention,
    ExtractionResult,
    ImageBlock,
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
    Entity,
    EntityFact,
    EntityFactLink,
    EntityLink,
    EntityTypeVocab,
    FactRoleVocab,
    FactTypeVocab,
    ItemNote,
    RawItem,
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
    ):
        self.db = db
        self.files = files
        self.engine = engine
        self.llm = llm
        self.embedder = embedder

    async def process_item(self, item_id: uuid.UUID) -> None:
        """Entity-centric pipeline for a single raw item."""
        async with self.db() as session:
            try:
                item = await session.get(RawItem, item_id)
                if not item:
                    # Belt-and-braces for enqueue-before-commit races. One
                    # short retry clears any producer that forgot to commit.
                    await asyncio.sleep(0.5)
                    item = await session.get(RawItem, item_id)
                if not item:
                    logger.error(f"Item {item_id} not found")
                    return

                item.status = "processing"
                item.processing_started_at = datetime.now(timezone.utc)
                await session.commit()

                notes_result = await session.execute(
                    select(ItemNote).where(ItemNote.item_id == item_id).order_by(ItemNote.created_at)
                )
                notes = notes_result.scalars().all()
                user_notes = None
                if notes:
                    user_notes = "\n\n---\n\n".join(
                        f"Note (added {n.created_at.isoformat()}):\n{n.content}" for n in notes
                    )

                content = await self._extract_content(item)
                if not content:
                    item.status = "error"
                    item.error_message = "No content could be extracted"
                    await session.commit()
                    return

                if item.content_text != content:
                    item.content_text = content

                # Conversation items take a self-extraction shortcut and skip
                # the entity-extraction pipeline entirely.
                if (item.content_type or "").lower() == "conversation":
                    from m3.core.self_extractor import extract_self_facts
                    touched = await extract_self_facts(
                        db_factory=self.db,
                        llm=self.llm,
                        transcript=content,
                    )
                    item.status = "done"
                    item.processed_at = datetime.now(timezone.utc)
                    await session.commit()
                    logger.info(
                        "Crystallized item %s: touched %d self entities",
                        item_id,
                        len(touched),
                    )
                    return

                content_type = (
                    ContentType(item.content_type)
                    if item.content_type in ContentType.__members__.values()
                    else ContentType.TEXT
                )

                content_blocks = await self._build_content_blocks(item, content)

                capabilities = getattr(self.engine, "capabilities", None)
                wants_multimodal = bool(capabilities and capabilities.multimodal) and any(
                    isinstance(b, (ImageBlock, AudioBlock)) for b in content_blocks
                )
                extract_input: str | list[ContentBlock] = (
                    content_blocks if wants_multimodal else content
                )

                extraction = await self.engine.extract(
                    content=extract_input, content_type=content_type, user_notes=user_notes,
                )
                n_facts, touched_ids = await self._persist_extraction(session, item, extraction)

                if touched_ids:
                    try:
                        await find_insights_for_touched(
                            session, self.engine, touched_ids,
                        )
                    except Exception:
                        logger.exception("find_insights raised; ingest continues")

                item.status = "done"
                item.processed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info(
                    f"Processed item {item_id}: {len(extraction.entities)} entities, "
                    f"{n_facts} facts, {len(extraction.relationships or [])} relationships"
                )

            except Exception as e:
                await session.rollback()
                async with self.db() as err_session:
                    err_item = await err_session.get(RawItem, item_id)
                    if err_item:
                        err_item.status = "error"
                        err_item.error_message = str(e)[:1000]
                        await err_session.commit()
                logger.exception(f"Failed to process item {item_id}")

    async def _build_content_blocks(
        self, item: RawItem, text_content: str,
    ) -> list[ContentBlock]:
        """Build the multimodal ContentBlock list for engines that support it."""
        blocks: list[ContentBlock] = []

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

        resolved: dict[tuple[str, str], Entity] = {}
        for mention in extraction.entities:
            outcome = await resolve_entity(session, self.embedder, self.llm, mention)
            key = (mention.canonical_name.lower(), mention.entity_type.lower())
            resolved[key] = outcome.entity
            for alias in mention.aliases or []:
                resolved.setdefault((alias.lower(), mention.entity_type.lower()), outcome.entity)
            await self._bump_type_vocab(session, EntityTypeVocab, outcome.entity.entity_type)

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

            # Two passes: pick the strongest role when the LLM emits the same
            # entity twice in one fact, then emit one fact-link per unique
            # entity. The PK on entity_fact_links is (fact_id, entity_id),
            # which a naive loop would violate.
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
                ent = next(e for e in resolved.values() if e.id == eid)
                session.add(EntityFactLink(fact_id=fact.id, entity_id=eid, role=role))
                await self._bump_type_vocab(session, FactRoleVocab, role)
                ent.page_dirty = True
                ent.facts_since_render = (ent.facts_since_render or 0) + 1
                linked_entity_ids.append(eid)

            persisted_facts += 1

            uniq = list(dict.fromkeys(linked_entity_ids))
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    pair = frozenset({uniq[i], uniq[j]})
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1

        await session.flush()

        for pair, count in pair_counts.items():
            a, b = sorted(pair, key=lambda x: str(x))
            await self._upsert_entity_link(session, a, b, "related", count)

        for rel in extraction.relationships or []:
            src = resolved.get((rel.source_name.lower(), rel.source_type.lower()))
            tgt = resolved.get((rel.target_name.lower(), rel.target_type.lower()))
            if src is None or tgt is None or src.id == tgt.id:
                continue
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
        if not name:
            return
        stmt = pg_insert(model.__table__).values(name=name, usage_count=1).on_conflict_do_update(
            index_elements=["name"],
            set_={"usage_count": model.__table__.c.usage_count + 1},
        )
        await session.execute(stmt)

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
            file_bytes = await self.files.download(item.file_path)
            filename = item.file_path.rsplit("/", 1)[-1]
            extracted = await extract_by_filename(file_bytes, filename)
            if extracted:
                return extracted
            return item.content_text or ""

        if item.content_type == "image" and item.file_path:
            image_bytes = await self.files.download(item.file_path)
            mime = "image/jpeg"
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
            mime = "audio/mp4"
            blocks = make_content_blocks(
                text="Transcribe this audio. Include a brief summary.",
                audio_bytes=audio_bytes,
                media_type=mime,
            )
            return await self.llm.complete(
                messages=[{"role": "user", "content": blocks}],
                max_tokens=4000,
            )

        return item.content_text or ""


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
