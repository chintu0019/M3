"""HTTP ingest surface: POST /api/v1/ingest/text (JSON body) and POST /api/v1/ingest/file (multipart)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable, Protocol

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from m3.core.ingest import IngestInput, Ingester


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class IngestTextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = "http"
    note: str | None = None


class IngestResponse(BaseModel):
    item_id: str
    kind: str
    confidence: float
    self_touched: list[str]
    entities_touched: list[str]
    questions_raised: int


def build_ingest_router(*, brain_root: Path, embedder: _Embedder, llm_factory: Callable | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["ingest"])

    def _get_llm():
        if llm_factory is None:
            raise HTTPException(status_code=503, detail="no LLM configured; set M3_LLM_PROVIDER")
        return llm_factory()

    @router.post("/ingest/text", response_model=IngestResponse)
    async def ingest_text(body: IngestTextRequest):
        return await _ingest_impl(
            brain_root=brain_root, embedder=embedder, llm=_get_llm(),
            source=body.source,
            original_bytes=None, original_filename=None,
            content_type="text", text=body.text, user_notes=body.note,
        )

    @router.post("/ingest/file", response_model=IngestResponse)
    async def ingest_file(
        file: UploadFile = File(...),
        source: str = Form("http"),
        note: str | None = Form(None),
    ):
        data = await file.read()
        filename = file.filename or "upload.bin"
        if filename.lower().endswith((".txt", ".md")):
            text = data.decode("utf-8", errors="replace")
            return await _ingest_impl(
                brain_root=brain_root, embedder=embedder, llm=_get_llm(),
                source=source, original_bytes=None, original_filename=filename,
                content_type="text", text=text, user_notes=note,
            )
        return await _ingest_impl(
            brain_root=brain_root, embedder=embedder, llm=_get_llm(),
            source=source, original_bytes=data, original_filename=filename,
            content_type=_guess_content_type(filename), text="", user_notes=note,
        )

    return router


async def _ingest_impl(*, brain_root, embedder, llm, source, original_bytes, original_filename,
                       content_type, text, user_notes) -> IngestResponse:
    ingester = Ingester(brain_root=brain_root, llm=llm, embedder=embedder)
    out = await ingester.ingest(IngestInput(
        item_id=uuid.uuid4(), source=source,
        original_bytes=original_bytes, original_filename=original_filename,
        content_type=content_type, text=text, user_notes=user_notes,
    ))
    return IngestResponse(
        item_id=str(out.item_id), kind=out.kind, confidence=out.confidence,
        self_touched=out.self_touched, entities_touched=out.entities_touched,
        questions_raised=out.questions_raised,
    )


def _guess_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf": return "pdf"
    if ext == "docx": return "docx"
    if ext in {"png", "jpg", "jpeg", "webp", "gif"}: return "image"
    if ext in {"m4a", "mp3", "wav", "ogg"}: return "audio"
    return "file"
