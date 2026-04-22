"""Ingest orchestrator: one raw item in, patched ~/brain/ out.

Sequence:
  1. Persist item original bytes + a placeholder meta JSON.
  2. Load self.md and the top-K entity candidates for prompt context.
  3. Call the LLM's process_item tool.
  4. Apply the diff operations to self.md and entity pages.
  5. Apply record / signal side-effects based on kind.
  6. Append open questions, changelog entries, and vector index upserts.
  7. Commit to ~/brain/.git.
"""

from __future__ import annotations

import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from m3.brain import (
    changelog,
    entity_doc,
    items as items_mod,
    questions,
    records as records_mod,
    self_doc,
    signals as signals_mod,
)
from m3.brain.git import commit_ingest
from m3.brain.vectors import VectorIndex
from m3.core.extract import (
    ExtractionOutput,
    build_system_prompt,
    process_item_tool_schema,
)
from m3.core.llm import LLMProvider, Tool

logger = logging.getLogger("m3.ingest")


class _Embedder(Protocol):
    dim: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class IngestInput:
    item_id: uuid.UUID
    source: str                             # telegram | share_sheet | drag_drop | cli | ...
    original_bytes: bytes | None
    original_filename: str | None
    content_type: str                       # text | pdf | image | audio | url | ...
    text: str                               # already-extracted text (extractors.py handles PDF etc upstream)
    user_notes: str | None = None


@dataclass
class IngestOutput:
    item_id: uuid.UUID
    kind: str
    confidence: float
    self_touched: list[str] = field(default_factory=list)
    entities_touched: list[str] = field(default_factory=list)
    questions_raised: int = 0


class Ingester:
    def __init__(self, *, brain_root: Path, llm: LLMProvider, embedder: _Embedder) -> None:
        self.brain_root = brain_root
        self.llm = llm
        self.embedder = embedder

    async def ingest(self, inp: IngestInput) -> IngestOutput:
        item_id_str = str(inp.item_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        today = now_iso[:10]

        try:
            # Everything from here through commit_ingest touches the brain tree.
            # If any step fails we roll back via `git reset --hard HEAD && git clean -fd`
            # so the tree is indistinguishable from its pre-ingest state. That includes
            # the originally-written bytes — so keep the write inside the try.
            if inp.original_bytes is not None:
                ext = (inp.original_filename or "bin").rsplit(".", 1)[-1] or "bin"
                items_mod.write_item(self.brain_root, inp.item_id, extension=ext, content=inp.original_bytes)

            candidates_block = await self._candidate_entities_prompt_block(inp.text)
            self_doc_text = (self.brain_root / "self.md").read_text()
            system = build_system_prompt(today_iso=today, self_doc=self_doc_text, candidate_entities_block=candidates_block)

            user_notes_block = f"\n\nUser notes: {inp.user_notes}" if inp.user_notes else ""
            user_msg = (
                f"Item id: {item_id_str}\nSource: {inp.source}\nContent type: {inp.content_type}\n"
                f"Ingested at: {now_iso}\n\n---\n{inp.text}\n---{user_notes_block}"
            )

            tool = Tool(
                name="process_item",
                description="Emit M3's structured extraction for this item.",
                input_schema=process_item_tool_schema(),
            )
            result = await self.llm.complete_tool(
                messages=[{"role": "user", "content": user_msg}],
                tools=[tool], system=system, tool_choice="process_item",
                max_tokens=8192, temperature=0.2,
            )
            parsed = ExtractionOutput.model_validate(result.input or {})

            # 1. Meta
            items_mod.write_meta(self.brain_root, items_mod.ItemMeta(
                id=inp.item_id, kind=parsed.kind, source=inp.source, created_at=now_iso,
                original_filename=inp.original_filename, extracted_text=inp.text,
                when_iso=parsed.interpretation.when.iso, when_source=parsed.interpretation.when.source,
                hooks=parsed.hooks.model_dump(), llm_output_raw=parsed.model_dump(),
                confidence=parsed.interpretation.confidence,
            ))

            # 2. Self updates
            self_touched: list[str] = []
            for su in parsed.self_updates:
                self_doc.apply_update(
                    self.brain_root, slot=su.slot, operation=su.operation,
                    new_content=su.new_content, heading=su.section_heading,
                )
                self_touched.append(su.slot)
                changelog.append(
                    self.brain_root, timestamp=now_iso,
                    target=f"self.md#{su.slot}", summary=su.change_summary,
                )

            # 3. Entity updates
            entities_touched: list[str] = []
            for eu in parsed.entity_updates:
                # Resolve the slug we're updating. match_existing_id carries a slug
                # from the candidate-entities block (P2 will make this richer).
                # If the LLM emits a rename (match_existing_slug != slug(canonical_name)),
                # consolidate() renames the file and folds in aliases.
                match_slug = eu.match_existing_id
                target_slug = match_slug or entity_doc.slugify(eu.canonical_name)
                existing = entity_doc.load(self.brain_root, slug=target_slug)
                related_slugs = [entity_doc.slugify(n) for n in (eu.related_entity_names or [])]
                new_body = existing.body if existing else ""
                if eu.section_update:
                    new_body = _apply_section_op(new_body, eu.section_update.operation,
                                                 eu.section_update.new_content, eu.section_update.section_heading)
                entity_doc.consolidate(
                    self.brain_root,
                    canonical_name=eu.canonical_name,
                    entity_type=eu.entity_type,
                    merge_aliases=list(eu.merge_aliases or []),
                    description=None,
                    related=related_slugs,
                    summary_external=eu.summary_external,
                    body=new_body,
                    match_existing_slug=match_slug,
                )
                entities_touched.append(eu.canonical_name)
                if eu.section_update:
                    changelog.append(
                        self.brain_root, timestamp=now_iso,
                        target=f"entities/{entity_doc.slugify(eu.canonical_name)}.md",
                        summary=eu.section_update.change_summary,
                    )

            # 4. Record / signal routing
            if parsed.kind == "record" and parsed.structured_fields is not None:
                sf = parsed.structured_fields
                # StructuredFields is now fully optional at the schema level to tolerate
                # partial LLM extractions. We still require amount/vendor/date before
                # writing a Record — anything less isn't a usable record row.
                if sf.amount is not None and sf.vendor and sf.date:
                    records_mod.write_record(self.brain_root, records_mod.Record(
                        item_id=inp.item_id, amount=sf.amount,
                        currency=sf.currency or "USD", vendor=sf.vendor,
                        date=sf.date, category=sf.category or "unknown",
                        due_date=sf.due_date, reference_id=sf.reference_id,
                    ))
                else:
                    logger.warning(
                        "record item %s has incomplete structured_fields "
                        "(amount=%s vendor=%s date=%s); skipping record write",
                        item_id_str, sf.amount, sf.vendor, sf.date,
                    )
            if parsed.kind == "signal" and parsed.signal is not None:
                sig = parsed.signal
                signals_mod.append_signal(self.brain_root, signals_mod.Signal(
                    item_id=inp.item_id, date=parsed.interpretation.when.iso or today,
                    topic_entities=list(sig.topic_entities), one_line_takeaway=sig.one_line_takeaway,
                ))
                for name in sig.topic_entities:
                    signals_mod.bump_mention_count(
                        self.brain_root,
                        canonical_name=name,
                        takeaway=sig.one_line_takeaway or None,
                        date=parsed.interpretation.when.iso or today,
                    )

            # 5. Open questions
            for oq in parsed.open_questions:
                questions.append(self.brain_root, questions.OpenQuestion(
                    item_id=inp.item_id, question=oq.question, context_snippet=oq.context_snippet,
                ), created_date=today)

            # 6. Vector index upserts
            await self._index_item(inp.item_id, inp.text, parsed, entities_touched)

            # 7. Commit
            summary = parsed.interpretation.what_happened[:120] or f"{parsed.kind} item"
            commit_ingest(self.brain_root, item_id=item_id_str, summary=summary)

            return IngestOutput(
                item_id=inp.item_id, kind=parsed.kind, confidence=parsed.interpretation.confidence,
                self_touched=self_touched, entities_touched=entities_touched,
                questions_raised=len(parsed.open_questions),
            )
        except Exception:
            # Reset to the last committed state so a partial ingest leaves nothing
            # behind — no orphan originals, no half-written metas, no stray entity
            # files. Relies on init_brain's baseline commit for first-run brains.
            self._rollback()
            raise

    def _rollback(self) -> None:
        try:
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=self.brain_root, check=True)
            subprocess.run(["git", "clean", "-fd"], cwd=self.brain_root, check=True)
        except subprocess.CalledProcessError:
            # We're already in an error handler; let the original exception propagate.
            logger.exception("git rollback failed; brain tree may be dirty")

    async def _candidate_entities_prompt_block(self, text: str) -> str:
        # P1 stub: we don't yet have enough entities for similarity retrieval to be meaningful.
        # The block is still required so the prompt shape stays stable from day one.
        # P2 will replace this with a real top-K lookup against VectorIndex.nearest_entities.
        return "(no candidate entities yet)"

    async def _index_item(self, item_id: uuid.UUID, text: str, parsed: ExtractionOutput, entities_touched: list[str]) -> None:
        from m3.brain.fts import FTSIndex
        from m3.brain.hooks import HookIndex

        if text.strip():
            vec = (await self.embedder.embed([text]))[0]
            vidx = VectorIndex.open(self.brain_root)
            try:
                vidx.upsert_item(item_id=str(item_id), embedding=vec)
                for name in entities_touched:
                    evec = (await self.embedder.embed([name]))[0]
                    vidx.upsert_entity(slug=entity_doc.slugify(name), embedding=evec)
            finally:
                vidx.close()

        if text.strip():
            fidx = FTSIndex.open(self.brain_root)
            try:
                fidx.upsert_item(item_id=str(item_id), text=text)
            finally:
                fidx.close()

        hidx = HookIndex.open(self.brain_root)
        try:
            hidx.upsert_item_hooks(
                item_id=str(item_id),
                who=[ref.name for ref in parsed.hooks.who],
                what=[ref.name for ref in parsed.hooks.what],
                where=[ref.name for ref in parsed.hooks.where],
                project=list(parsed.hooks.project or []),
                stance_entities=[s.entity_name for s in parsed.hooks.stance],
            )
        finally:
            hidx.close()


def _apply_section_op(body: str, operation: str, new_content: str, heading: str | None) -> str:
    """Apply an entity-body section op. Entity bodies are free-form markdown, not fixed slots."""
    if operation == "append":
        return (body.rstrip() + "\n\n" + new_content.strip()).strip() + "\n" if body.strip() else new_content.strip() + "\n"
    if operation in {"replace_section", "revise"}:
        if not heading:
            raise ValueError(f"{operation} requires a section_heading")
        if heading not in body:
            return (body.rstrip() + "\n\n" + new_content.strip()).strip() + "\n"   # fallback: append if heading missing
        import re
        sibling = re.compile(r"^#{2,4} .+$", re.MULTILINE)
        matches = list(sibling.finditer(body))
        for i, m in enumerate(matches):
            if body[m.start():m.end()].strip() == heading.strip():
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
                return (body[:start] + new_content.rstrip() + "\n\n" + body[end:]).strip() + "\n"
        return (body.rstrip() + "\n\n" + new_content.strip()).strip() + "\n"
    raise ValueError(f"unknown section op: {operation!r}")
