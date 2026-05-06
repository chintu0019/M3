"""HTTP surface for items: metadata, originals, list, provenance, text, thumbnail, archive, reingest."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from m3.brain.items import ItemMeta, iter_metas, read_meta, write_meta
from m3.brain.layout import BrainPaths

logger = logging.getLogger("m3.api.items")


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ItemMetaModel(BaseModel):
    id: str
    kind: str
    source: str
    created_at: str
    original_filename: str | None = None
    extracted_text: str
    when_iso: str | None = None
    when_source: str
    hooks: dict
    confidence: float
    archived: bool = False


class ItemListEntry(BaseModel):
    id: str
    kind: str
    content_kind: str
    source: str
    original_filename: str | None
    created_at: str
    when_iso: str | None
    confidence: float
    snippet: str
    entity_count: int
    has_original: bool
    has_thumbnail: bool
    extension: str | None
    archived: bool


class ItemListPage(BaseModel):
    items: list[ItemListEntry]
    next_cursor: str | None = None
    total: int


class ProvenanceEntity(BaseModel):
    slug: str
    canonical_name: str
    entity_type: str | None = None
    role: str   # created | updated | merged


class ProvenanceFact(BaseModel):
    text: str
    source: str   # self_updates | entity_updates | hooks


class ProvenanceResponse(BaseModel):
    item_id: str
    entities_touched: list[ProvenanceEntity]
    facts: list[ProvenanceFact]
    questions: list[str]
    signal: dict | None = None
    record: dict | None = None


class ItemTextResponse(BaseModel):
    extracted_text: str
    truncated: bool


class ArchiveBody(BaseModel):
    archived: bool


_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}
_AUDIO_EXTS = {"m4a", "mp3", "wav", "ogg", "flac", "aac"}
_VIDEO_EXTS = {"mp4", "mov", "mkv", "webm", "avi"}
_TEXT_EXTS = {"txt", "md", "markdown", "rst", "log"}


def _content_kind_for_extension(ext: str) -> str:
    e = (ext or "").lstrip(".").lower()
    if e == "pdf":
        return "pdf"
    if e == "docx":
        return "docx"
    if e in _IMAGE_EXTS:
        return "image"
    if e in _AUDIO_EXTS:
        return "audio"
    if e in _VIDEO_EXTS:
        return "video"
    if e in _TEXT_EXTS:
        return "text"
    return "file"


def _content_kind_for(meta: ItemMeta, paths: BrainPaths) -> tuple[str, str | None, bool]:
    """Return (content_kind, extension, has_original) for a persisted item.

    Looks at the on-disk original first (the canonical source of file type),
    then falls back to the extension on `original_filename`. Items with no
    bytes at all (pure text ingests) report content_kind="text".
    """
    candidates = list(paths.items_originals.glob(f"{meta.id}.*"))
    if candidates:
        ext = candidates[0].suffix.lstrip(".")
        return _content_kind_for_extension(ext), ext, True
    if meta.original_filename and "." in meta.original_filename:
        ext = meta.original_filename.rsplit(".", 1)[-1]
        return _content_kind_for_extension(ext), ext, False
    return "text", None, False


def _entity_count_from_hooks(hooks: dict[str, Any]) -> int:
    n = 0
    for key in ("who", "what", "where", "stance"):
        v = hooks.get(key) or []
        n += len(v) if isinstance(v, list) else 0
    return n


def _snippet(text: str, n: int = 160) -> str:
    s = (text or "").strip().replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def _encode_cursor(created_at: str, item_id: str) -> str:
    raw = json.dumps({"created_at": created_at, "id": item_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str] | None:
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + pad)
        d = json.loads(raw)
        return str(d["created_at"]), str(d["id"])
    except Exception:
        return None


def build_items_router(
    *,
    brain_root: Path,
    embedder: _Embedder | None = None,
    llm_factory: Callable | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["items"])

    @router.get("/items", response_model=ItemListPage)
    async def list_items(
        kind: list[str] | None = Query(None),
        content_kind: list[str] | None = Query(None),
        q: str | None = Query(None),
        since_iso: str | None = Query(None),
        until_iso: str | None = Query(None),
        cursor: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        include_archived: bool = Query(False),
    ):
        paths = BrainPaths(brain_root)
        all_metas = list(iter_metas(brain_root))

        # Pre-compute content_kind / has_original once per row so we can both
        # filter on it and emit it in the response without hitting the disk
        # twice. Cheap enough for low-thousand-item brains.
        rows: list[tuple[ItemMeta, str, str | None, bool]] = []
        for meta in all_metas:
            ck, ext, has_orig = _content_kind_for(meta, paths)
            rows.append((meta, ck, ext, has_orig))

        def matches(row: tuple[ItemMeta, str, str | None, bool]) -> bool:
            meta, ck, _ext, _has = row
            if not include_archived and meta.archived:
                return False
            if kind and meta.kind not in kind:
                return False
            if content_kind and ck not in content_kind:
                return False
            if q:
                needle = q.lower()
                hay = (meta.original_filename or "").lower() + " " + (meta.extracted_text or "")[:500].lower()
                if needle not in hay:
                    return False
            if since_iso and meta.created_at < since_iso:
                return False
            if until_iso and meta.created_at > until_iso:
                return False
            return True

        filtered = [r for r in rows if matches(r)]
        # Sort: newest first by created_at, with id as a stable tie-break.
        filtered.sort(key=lambda r: (r[0].created_at, str(r[0].id)), reverse=True)

        # Cursor = (created_at, id) of the last item from the previous page;
        # we return everything *strictly older* than that anchor.
        if cursor:
            decoded = _decode_cursor(cursor)
            if decoded is not None:
                anchor_ts, anchor_id = decoded
                filtered = [
                    r for r in filtered
                    if (r[0].created_at, str(r[0].id)) < (anchor_ts, anchor_id)
                ]

        total = len(filtered)
        page = filtered[:limit]
        next_cursor: str | None = None
        if len(filtered) > limit:
            last = page[-1][0]
            next_cursor = _encode_cursor(last.created_at, str(last.id))

        thumbs_dir = paths.root / "items" / "thumbs"

        entries: list[ItemListEntry] = []
        for meta, ck, ext, has_orig in page:
            entries.append(ItemListEntry(
                id=str(meta.id),
                kind=meta.kind,
                content_kind=ck,
                source=meta.source,
                original_filename=meta.original_filename,
                created_at=meta.created_at,
                when_iso=meta.when_iso,
                confidence=meta.confidence,
                snippet=_snippet(meta.extracted_text),
                entity_count=_entity_count_from_hooks(meta.hooks or {}),
                has_original=has_orig,
                has_thumbnail=(thumbs_dir / f"{meta.id}.jpg").exists(),
                extension=ext,
                archived=meta.archived,
            ))

        return ItemListPage(items=entries, next_cursor=next_cursor, total=total)

    @router.get("/items/{item_id}", response_model=ItemMetaModel)
    async def get_item(item_id: str):
        meta = _load_or_404(brain_root, item_id)
        return ItemMetaModel(
            id=str(meta.id),
            kind=meta.kind,
            source=meta.source,
            created_at=meta.created_at,
            original_filename=meta.original_filename,
            extracted_text=meta.extracted_text,
            when_iso=meta.when_iso,
            when_source=meta.when_source,
            hooks=meta.hooks,
            confidence=meta.confidence,
            archived=meta.archived,
        )

    @router.get("/items/{item_id}/original")
    async def get_item_original(item_id: str):
        try:
            uid = uuid.UUID(item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid uuid")
        p = BrainPaths(brain_root)
        candidates = list(p.items_originals.glob(f"{uid}.*"))
        if not candidates:
            raise HTTPException(status_code=404, detail=f"no original bytes for {item_id}")
        return FileResponse(candidates[0])

    @router.get("/items/{item_id}/thumbnail")
    async def get_item_thumbnail(item_id: str):
        try:
            uid = uuid.UUID(item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid uuid")
        thumb = brain_root / "items" / "thumbs" / f"{uid}.jpg"
        if not thumb.exists():
            raise HTTPException(status_code=404, detail="no thumbnail")
        return FileResponse(thumb, media_type="image/jpeg")

    @router.get("/items/{item_id}/text", response_model=ItemTextResponse)
    async def get_item_text(item_id: str, max_chars: int = Query(20000, ge=1, le=200000)):
        meta = _load_or_404(brain_root, item_id)
        text = meta.extracted_text or ""
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return ItemTextResponse(extracted_text=text, truncated=truncated)

    @router.get("/items/{item_id}/provenance", response_model=ProvenanceResponse)
    async def get_item_provenance(item_id: str):
        meta = _load_or_404(brain_root, item_id)
        raw = meta.llm_output_raw or {}
        entities: list[ProvenanceEntity] = []
        for eu in raw.get("entity_updates") or []:
            name = eu.get("canonical_name") or ""
            if not name:
                continue
            slug = eu.get("match_existing_id") or _slugify(name)
            entities.append(ProvenanceEntity(
                slug=slug,
                canonical_name=name,
                entity_type=eu.get("entity_type"),
                role="updated",
            ))
        facts: list[ProvenanceFact] = []
        for su in raw.get("self_updates") or []:
            text = su.get("change_summary") or su.get("new_content") or ""
            if text:
                facts.append(ProvenanceFact(text=text, source="self_updates"))
        for eu in raw.get("entity_updates") or []:
            sec = eu.get("section_update") or {}
            text = sec.get("change_summary") or sec.get("new_content") or ""
            if text:
                facts.append(ProvenanceFact(text=text, source="entity_updates"))
        # Hooks contribute lightweight facts too — mention which entities the
        # ingest associated with this item, even when no entity_update was made.
        hooks = meta.hooks or {}
        for hk in ("who", "what", "where"):
            for ref in hooks.get(hk) or []:
                name = ref.get("name") if isinstance(ref, dict) else ref
                if name:
                    facts.append(ProvenanceFact(text=f"{hk}: {name}", source="hooks"))
        questions = [q.get("question") for q in (raw.get("open_questions") or []) if q.get("question")]
        return ProvenanceResponse(
            item_id=str(meta.id),
            entities_touched=entities,
            facts=facts,
            questions=questions,
            signal=raw.get("signal"),
            record=raw.get("structured_fields"),
        )

    @router.post("/items/{item_id}/archive")
    async def archive_item(item_id: str, body: ArchiveBody):
        meta = _load_or_404(brain_root, item_id)
        if meta.archived == body.archived:
            return {"ok": True, "archived": meta.archived, "no_op": True}
        meta.archived = body.archived
        write_meta(brain_root, meta)
        if body.archived:
            _drop_indexes(brain_root, item_id)
            commit_msg = f"chore: archive item {item_id}"
        else:
            await _restore_indexes(brain_root, meta, embedder)
            commit_msg = f"chore: unarchive item {item_id}"
        _commit_chore(brain_root, commit_msg)
        return {"ok": True, "archived": meta.archived}

    @router.post("/items/{item_id}/reingest")
    async def reingest_item(item_id: str):
        if llm_factory is None:
            raise HTTPException(status_code=503, detail="no LLM configured; set M3_LLM_PROVIDER")
        if embedder is None:
            raise HTTPException(status_code=503, detail="server has no embedder")
        meta = _load_or_404(brain_root, item_id)
        paths = BrainPaths(brain_root)
        # Try to reuse the original file bytes if we still have them. Falls back
        # to the previously-extracted text when the file is text-only.
        candidates = list(paths.items_originals.glob(f"{meta.id}.*"))
        original_bytes: bytes | None = None
        original_filename = meta.original_filename
        content_type = "text"
        if candidates:
            original_bytes = candidates[0].read_bytes()
            ext = candidates[0].suffix.lstrip(".")
            content_type = _content_kind_for_extension(ext)
            if not original_filename:
                original_filename = candidates[0].name
        from m3.core.ingest import IngestInput, Ingester  # local import to avoid cycle
        ingester = Ingester(brain_root=brain_root, llm=llm_factory(), embedder=embedder)
        # Reuse the existing item_id so the meta + indexes overwrite in-place.
        result = await ingester.ingest(IngestInput(
            item_id=meta.id,
            source=f"reingest:{meta.source}",
            original_bytes=original_bytes,
            original_filename=original_filename,
            content_type=content_type,
            text=meta.extracted_text or "",
            user_notes=None,
        ))
        return {
            "item_id": str(result.item_id),
            "kind": result.kind,
            "confidence": result.confidence,
            "self_touched": result.self_touched,
            "entities_touched": result.entities_touched,
            "questions_raised": result.questions_raised,
        }

    return router


def _load_or_404(brain_root: Path, item_id: str) -> ItemMeta:
    try:
        uid = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid uuid")
    meta = read_meta(brain_root, uid)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found")
    return meta


def _slugify(name: str) -> str:
    # Avoid importing entity_doc just for slug; keep this in lockstep with
    # the entity_doc.slugify() rule (lowercase, hyphenated). The provenance
    # response is read-only so a slight skew here only mis-links a chip.
    import re
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def _drop_indexes(brain_root: Path, item_id: str) -> None:
    """Remove an item from FTS + vectors + hooks. Used on archive/delete."""
    from m3.brain.fts import FTSIndex
    from m3.brain.hooks import HookIndex
    from m3.brain.vectors import VectorIndex
    fidx = FTSIndex.open(brain_root)
    try:
        fidx._conn.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        fidx._conn.commit()
    finally:
        fidx.close()
    vidx = VectorIndex.open(brain_root)
    try:
        vidx._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        vidx._conn.commit()
    finally:
        vidx.close()
    hidx = HookIndex.open(brain_root)
    try:
        hidx.delete_item(item_id=item_id)
    finally:
        hidx.close()


async def _restore_indexes(brain_root: Path, meta: ItemMeta, embedder: _Embedder | None) -> None:
    """Re-insert FTS + vector + hook rows from a meta. Symmetrical to _drop_indexes."""
    from m3.brain.fts import FTSIndex
    from m3.brain.hooks import HookIndex
    text = meta.extracted_text or ""
    if text.strip():
        fidx = FTSIndex.open(brain_root)
        try:
            fidx.upsert_item(item_id=str(meta.id), text=text)
        finally:
            fidx.close()
        if embedder is not None:
            from m3.brain.vectors import VectorIndex
            vec = (await embedder.embed([text]))[0]
            vidx = VectorIndex.open(brain_root)
            try:
                vidx.upsert_item(item_id=str(meta.id), embedding=vec)
            finally:
                vidx.close()
    hooks = meta.hooks or {}

    def _names(key: str) -> list[str]:
        out: list[str] = []
        for ref in hooks.get(key) or []:
            if isinstance(ref, dict) and ref.get("name"):
                out.append(ref["name"])
            elif isinstance(ref, str):
                out.append(ref)
        return out

    hidx = HookIndex.open(brain_root)
    try:
        hidx.upsert_item_hooks(
            item_id=str(meta.id),
            who=_names("who"),
            what=_names("what"),
            where=_names("where"),
            project=list(hooks.get("project") or []),
            stance_entities=[s.get("entity_name") for s in (hooks.get("stance") or []) if isinstance(s, dict) and s.get("entity_name")],
        )
    finally:
        hidx.close()


def _commit_chore(brain_root: Path, message: str) -> None:
    """Stage + commit a non-ingest change to ~/brain/. Silent if there's nothing to commit."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=brain_root, check=True,
            capture_output=True, text=True,
        )
        if not status.stdout.strip():
            return
        subprocess.run(["git", "add", "-A"], cwd=brain_root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=brain_root, check=True)
    except subprocess.CalledProcessError:
        logger.exception("chore commit failed: %s", message)
