"""HTTP surface for entities (list + detail)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from m3.brain.entity_doc import EntityDoc, load
from m3.brain.layout import BrainPaths


class EntityModel(BaseModel):
    slug: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    related: list[str] = Field(default_factory=list)
    signal_mentions: int = 0
    summary_external: str | None = None
    body: str = ""


class EntityListResponse(BaseModel):
    entities: list[EntityModel]


def _to_model(slug: str, doc: EntityDoc) -> EntityModel:
    return EntityModel(
        slug=slug,
        canonical_name=doc.canonical_name,
        entity_type=doc.entity_type,
        aliases=doc.aliases,
        description=doc.description,
        related=doc.related,
        signal_mentions=doc.signal_mentions,
        summary_external=doc.summary_external,
        body=doc.body,
    )


def build_entities_router(*, brain_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["entities"])

    @router.get("/entities", response_model=EntityListResponse)
    async def list_entities():
        p = BrainPaths(brain_root)
        out: list[EntityModel] = []
        for md in sorted(p.entities_dir.glob("*.md")):
            slug = md.stem
            doc = load(brain_root, slug=slug)
            if doc is not None:
                out.append(_to_model(slug, doc))
        return EntityListResponse(entities=out)

    @router.get("/entities/{slug}", response_model=EntityModel)
    async def get_entity(slug: str):
        doc = load(brain_root, slug=slug)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"entity {slug!r} not found")
        return _to_model(slug, doc)

    return router
