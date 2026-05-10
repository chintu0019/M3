"""Topical signature texts + refresh orchestrators.

Each canvas node type contributes a different chunk of text that best
represents what the node is *about*; the embedding of that chunk goes
into the TopicalIndex and drives force layout in canvas v2.

Storage scheme: TopicalIndex (sqlite-vec) keyed by canvas node id, e.g.:
    entity:<slug> | item:<uuid> | claim:<uuid> | synthesis:<entity_slug>
"""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path
from typing import Protocol

from m3.brain.claims import ClaimMeta
from m3.brain.entity_doc import EntityDoc
from m3.brain.synthesis import SynthesisMeta
from m3.brain.topical import TopicalIndex


ITEM_SIG_CAP = 500


class _Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# --- pure signature-text functions ---


def signature_text_for_entity(doc: EntityDoc) -> str:
    parts = [doc.canonical_name, doc.entity_type or "", doc.body or ""]
    return "\n".join(p.strip() for p in parts if p and p.strip()).strip()


def signature_text_for_claim(claim: ClaimMeta) -> str:
    return claim.proposition.strip()


def signature_text_for_item(extracted_text: str | None) -> str:
    if not extracted_text:
        return ""
    return extracted_text[:ITEM_SIG_CAP]


def signature_text_for_synthesis(synth: SynthesisMeta) -> str:
    return (synth.summary or "").strip()


# --- refresh orchestrators ---


async def refresh_for_entity(
    *, brain_root: Path, slug: str, doc: EntityDoc, embedder: _Embedder,
) -> None:
    """Compute the entity's signature, embed it, upsert into the topical index.
    No-op if the signature is empty (e.g. a freshly-created stub entity)."""
    text = signature_text_for_entity(doc)
    if not text:
        return
    vec = (await embedder.embed([text]))[0]
    idx = TopicalIndex.open(brain_root)
    try:
        idx.upsert(f"entity:{slug}", vec)
    finally:
        idx.close()


async def refresh_for_item(
    *, brain_root: Path, item_id: _uuid.UUID, extracted_text: str | None,
    embedder: _Embedder,
) -> None:
    text = signature_text_for_item(extracted_text)
    if not text:
        return
    vec = (await embedder.embed([text]))[0]
    idx = TopicalIndex.open(brain_root)
    try:
        idx.upsert(f"item:{item_id}", vec)
    finally:
        idx.close()


async def refresh_for_claim(
    *, brain_root: Path, claim: ClaimMeta, embedder: _Embedder,
) -> None:
    text = signature_text_for_claim(claim)
    if not text:
        return
    vec = (await embedder.embed([text]))[0]
    idx = TopicalIndex.open(brain_root)
    try:
        idx.upsert(f"claim:{claim.id}", vec)
    finally:
        idx.close()


async def refresh_for_synthesis(
    *, brain_root: Path, synth: SynthesisMeta, embedder: _Embedder,
) -> None:
    text = signature_text_for_synthesis(synth)
    if not text:
        return
    vec = (await embedder.embed([text]))[0]
    idx = TopicalIndex.open(brain_root)
    try:
        idx.upsert(f"synthesis:{synth.entity_slug}", vec)
    finally:
        idx.close()
