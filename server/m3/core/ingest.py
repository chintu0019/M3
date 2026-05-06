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

import json as _json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

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
    Interpretation,
    OpenQuestionOut,
    When,
    build_system_prompt,
    process_item_tool_schema,
)
from m3.core.llm import LLMProvider, Tool

logger = logging.getLogger("m3.ingest")


MAX_EXTRACTION_RETRIES = 1   # total attempts = 1 + retries


def _short(exc: Exception, max_chars: int = 400) -> str:
    s = str(exc)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def _safe_json(data: dict | None, max_chars: int = 1500) -> str:
    if not data:
        return "{}"
    try:
        s = _json.dumps(data, default=str, indent=2)
    except (TypeError, ValueError):
        s = str(data)
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def _fallback_extraction(text: str) -> ExtractionOutput:
    """Build a minimal ExtractionOutput for items whose LLM output failed validation
    twice. Kind is "unknown", confidence 0.0, and we raise an open question so the
    user sees the miss. The raw item text still flows into FTS/hook indexes via the
    outer pipeline, which is the whole point — the item stays searchable."""
    snippet = (text or "").strip()[:200]
    return ExtractionOutput(
        kind="unknown",
        interpretation=Interpretation(
            what_happened=f"[extraction failed] {snippet}" if snippet else "[extraction failed]",
            when=When(iso=None, source="unknown"),
            confidence=0.0,
        ),
        open_questions=[
            OpenQuestionOut(
                question="Extraction failed; manual review needed.",
                context_snippet=snippet,
                blocks=[],
            ),
        ],
    )


class DegradedReprocessError(Exception):
    """Raised when a re-ingest would strictly worsen an item's existing meta.

    `reprocess_one` (and friends) catch this so a flaky LLM retry can't corrupt
    a previously-good item: the old meta stays, the brain's derived state is
    unchanged, and the user sees a clear skip reason.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _extraction_is_hollow(parsed: ExtractionOutput) -> bool:
    """Empty self_updates AND empty entity_updates AND no hooks that mention entities.
    'Hollow' means the LLM returned a valid shape but with nothing useful inside —
    typically the result of a retry prompt where the model picked a minimal path."""
    if parsed.self_updates or parsed.entity_updates:
        return False
    h = parsed.hooks
    hook_entity_count = len(h.who) + len(h.what) + len(h.where) + len(h.stance)
    if hook_entity_count > 0:
        return False
    # structured_fields / signal count as "useful" for record/signal kinds
    if parsed.structured_fields is not None or parsed.signal is not None:
        return False
    return True


def _detect_degradation(old_meta: "items_mod.ItemMeta | None", new_parsed: ExtractionOutput) -> str | None:
    """Return a human-readable reason if the new extraction degrades the old meta,
    else None. 'Degrades' means at least one of:
    - old kind was useful (not unknown), new is unknown
    - old had non-hollow extraction, new is hollow
    """
    if old_meta is None:
        return None   # nothing to degrade from
    if old_meta.kind != "unknown" and new_parsed.kind == "unknown":
        return f"new kind=unknown would degrade existing kind={old_meta.kind!r}"
    old_raw = old_meta.llm_output_raw or {}
    old_had_updates = bool(old_raw.get("self_updates") or old_raw.get("entity_updates"))
    old_hooks = old_raw.get("hooks") or {}
    old_had_hook_entities = any(bool(old_hooks.get(k)) for k in ("who", "what", "where", "stance"))
    old_was_useful = old_had_updates or old_had_hook_entities \
        or old_raw.get("structured_fields") is not None \
        or old_raw.get("signal") is not None
    if old_was_useful and _extraction_is_hollow(new_parsed):
        return (
            "new extraction is hollow (no self_updates, entity_updates, or hooks) "
            "but existing meta had content"
        )
    return None


def _repair_message(exc: ValidationError) -> str:
    """Craft a compact corrective prompt from a Pydantic ValidationError."""
    errors = exc.errors()
    lines = []
    for err in errors[:10]:
        loc = ".".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "validation error")
        lines.append(f"  - {loc}: {msg}")
    joined = "\n".join(lines)
    return (
        "Your previous tool call output did not match the process_item schema. "
        "These fields failed validation:\n"
        f"{joined}\n\n"
        "Call process_item AGAIN with a corrected payload. Same rules apply: "
        "no hallucination, diff-aware updates, classify into one of "
        "personal | reference | record | signal. Fix only the listed fields; "
        "keep everything else the same."
    )


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

    async def ingest(self, inp: IngestInput, *, refuse_if_degraded: bool = False) -> IngestOutput:
        """Run the full ingest pipeline for one item.

        If `refuse_if_degraded` is True, we compare the new extraction against
        any existing meta before applying. When the new extraction would worsen
        the existing meta (fallback-kind when we had a real kind, or a hollow
        extraction when we had real updates), raise `DegradedReprocessError`.
        The outer try/except rolls back so the existing brain state is preserved.
        """
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
                original_path = items_mod.write_item(
                    self.brain_root, inp.item_id, extension=ext, content=inp.original_bytes,
                )
                # Generate a list-view thumbnail. Best-effort: failures don't
                # block the ingest — we just fall back to the kind icon in UI.
                from m3.brain.thumbnails import generate_thumbnail
                generate_thumbnail(
                    self.brain_root, inp.item_id,
                    original_path=original_path, content_kind=inp.content_type,
                )

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
            async def _extract_with_retry() -> ExtractionOutput:
                last_err: Exception | None = None
                last_raw: dict | None = None
                attempt_messages: list = [{"role": "user", "content": user_msg}]
                for attempt in range(MAX_EXTRACTION_RETRIES + 1):
                    result = await self.llm.complete_tool(
                        messages=attempt_messages, tools=[tool], system=system,
                        tool_choice="process_item", max_tokens=8192, temperature=0.2,
                    )
                    try:
                        return ExtractionOutput.model_validate(result.input or {})
                    except ValidationError as e:
                        last_err = e
                        last_raw = result.input or {}
                        if attempt >= MAX_EXTRACTION_RETRIES:
                            break
                        logger.warning(
                            "ingest %s: extraction validation failed on attempt %d: %s",
                            item_id_str, attempt + 1, _short(e),
                        )
                        attempt_messages = attempt_messages + [
                            {"role": "assistant", "content": f"<attempted output>\n{_safe_json(last_raw)}\n</attempted output>"},
                            {"role": "user", "content": _repair_message(e)},
                        ]
                assert last_err is not None
                raise last_err

            extraction_error: str | None = None
            try:
                parsed = await _extract_with_retry()
            except ValidationError as e:
                # Graceful degradation: the LLM couldn't produce a valid schema even
                # after the corrective retry. Instead of rolling back and losing the
                # item entirely, write a minimal "unknown"-kind meta so the raw text
                # still lands in FTS/hook indexes and the user can find + re-trigger
                # the item via keyword search. Only catches ValidationError — other
                # exceptions (I/O, LLM transport failures) still roll back.
                extraction_error = _short(e, max_chars=500)
                logger.warning(
                    "ingest %s: extraction failed after retries; writing fallback meta. error: %s",
                    item_id_str, extraction_error,
                )
                parsed = _fallback_extraction(inp.text)

            # Reprocess guard: if the caller asked us to preserve the existing
            # meta on degradation, check now — before we overwrite it or touch
            # downstream state. This catches the "qwen hallucinated a minimal
            # payload on retry" case we saw in real use on 2026-04-23.
            if refuse_if_degraded:
                existing_meta = items_mod.read_meta(self.brain_root, inp.item_id)
                reason = _detect_degradation(existing_meta, parsed)
                if reason is not None:
                    raise DegradedReprocessError(reason)

            # 1. Meta
            llm_output_raw = parsed.model_dump()
            if extraction_error is not None:
                llm_output_raw["_extraction_error"] = extraction_error
            items_mod.write_meta(self.brain_root, items_mod.ItemMeta(
                id=inp.item_id, kind=parsed.kind, source=inp.source, created_at=now_iso,
                original_filename=inp.original_filename, extracted_text=inp.text,
                when_iso=parsed.interpretation.when.iso, when_source=parsed.interpretation.when.source,
                hooks=parsed.hooks.model_dump(), llm_output_raw=llm_output_raw,
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
                    if signals_mod.graduate_if_ready(self.brain_root, canonical_name=name):
                        changelog.append(
                            self.brain_root, timestamp=now_iso,
                            target=f"entities/{entity_doc.slugify(name)}.md",
                            summary="graduated from signals (>=3 mentions)",
                        )

            # 5. Open questions
            for oq in parsed.open_questions:
                questions.append(self.brain_root, questions.OpenQuestion(
                    item_id=inp.item_id, question=oq.question, context_snippet=oq.context_snippet,
                ), created_date=today)

            # 6. Vector index upserts
            await self._index_item(inp.item_id, inp.text, parsed, entities_touched)

            # 7. Commit
            if extraction_error is not None:
                snippet = (inp.text or "").strip()[:50]
                summary = f"[extraction failed] {snippet}" if snippet else "[extraction failed]"
            else:
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
