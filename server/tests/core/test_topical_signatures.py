import asyncio
import uuid as _uuid
from pathlib import Path

import pytest

from m3.brain.entity_doc import EntityDoc
from m3.brain.claims import ClaimMeta
from m3.brain.synthesis import SynthesisMeta
from m3.brain.topical import TopicalIndex
from m3.core.topical import (
    refresh_for_entity,
    refresh_for_item,
    refresh_for_claim,
    refresh_for_synthesis,
    signature_text_for_entity,
    signature_text_for_claim,
    signature_text_for_item,
    signature_text_for_synthesis,
)


def test_entity_signature_combines_name_type_and_body():
    doc = EntityDoc(
        canonical_name="Manoj Kesavulu",
        entity_type="person",
        body="CTO at Acme. Holds a PhD in software engineering.",
    )
    text = signature_text_for_entity(doc)
    assert "Manoj Kesavulu" in text
    assert "person" in text
    assert "CTO at Acme" in text


def test_claim_signature_is_proposition_only():
    claim = ClaimMeta(
        id=_uuid.uuid4(),
        item_id=_uuid.uuid4(),
        proposition="Project PACIFIC Phase 1 ships on June 14.",
        confidence=0.8,
        supporting_span="...",
        entity_slugs=["pacific"],
    )
    assert signature_text_for_claim(claim) == "Project PACIFIC Phase 1 ships on June 14."


def test_item_signature_caps_at_500_chars():
    long_text = "abcdefghij" * 100  # 1000 chars
    sig = signature_text_for_item(long_text)
    assert len(sig) == 500
    assert sig == "abcdefghij" * 50


def test_synthesis_signature_is_summary():
    synth = SynthesisMeta(
        id=_uuid.uuid4(),
        entity_slug="pacific",
        summary="PACIFIC is a security-focused launch pacing toward June 14.",
    )
    assert signature_text_for_synthesis(synth) == (
        "PACIFIC is a security-focused launch pacing toward June 14."
    )


def test_empty_inputs_return_empty_string():
    assert signature_text_for_item("") == ""
    assert signature_text_for_item(None) == ""


# --- refresh_for_* integration tests ---

class FakeEmbedder:
    """Deterministic 768-dim embedder. Vector value scales with input text length so we
    can sanity-check 'something different got embedded'."""
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(t)) / 1000.0] * 768 for t in texts]


def test_refresh_for_entity_writes_to_index(tmp_brain: Path):
    doc = EntityDoc(
        canonical_name="Manoj",
        entity_type="person",
        body="CTO at Acme.",
    )
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_entity(
        brain_root=tmp_brain, slug="manoj", doc=doc, embedder=embedder,
    ))
    idx = TopicalIndex.open(tmp_brain)
    vec = idx.get("entity:manoj")
    assert vec is not None
    assert len(vec) == 768
    assert len(embedder.calls) == 1


def test_refresh_for_entity_skips_empty_signature(tmp_brain: Path):
    doc = EntityDoc(canonical_name="", entity_type="", body="")
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_entity(
        brain_root=tmp_brain, slug="x", doc=doc, embedder=embedder,
    ))
    assert embedder.calls == []
    assert TopicalIndex.open(tmp_brain).get("entity:x") is None


def test_refresh_for_item_writes_to_index(tmp_brain: Path):
    item_id = _uuid.uuid4()
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_item(
        brain_root=tmp_brain, item_id=item_id,
        extracted_text="Some long ingested text about a project.",
        embedder=embedder,
    ))
    idx = TopicalIndex.open(tmp_brain)
    vec = idx.get(f"item:{item_id}")
    assert vec is not None
    assert len(vec) == 768


def test_refresh_for_item_skips_empty_text(tmp_brain: Path):
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_item(
        brain_root=tmp_brain, item_id=_uuid.uuid4(),
        extracted_text="", embedder=embedder,
    ))
    assert embedder.calls == []


def test_refresh_for_claim_writes_to_index(tmp_brain: Path):
    claim = ClaimMeta(
        id=_uuid.uuid4(),
        item_id=_uuid.uuid4(),
        proposition="A real claim.",
        confidence=0.9,
        supporting_span="...",
    )
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_claim(brain_root=tmp_brain, claim=claim, embedder=embedder))
    idx = TopicalIndex.open(tmp_brain)
    assert idx.get(f"claim:{claim.id}") is not None


def test_refresh_for_synthesis_writes_to_index(tmp_brain: Path):
    synth = SynthesisMeta(
        id=_uuid.uuid4(), entity_slug="pacific",
        summary="PACIFIC is winding down.",
    )
    embedder = FakeEmbedder()
    asyncio.run(refresh_for_synthesis(brain_root=tmp_brain, synth=synth, embedder=embedder))
    idx = TopicalIndex.open(tmp_brain)
    assert idx.get("synthesis:pacific") is not None
