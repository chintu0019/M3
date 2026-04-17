"""
M3 Compilation Engine — Base Interface

This is the abstraction that separates what's open-source from what's private.
The BasicEngine ships with M3 and works fine.
Custom engines can be loaded via config.yml engine_path.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    PDF = "pdf"
    URL = "url"
    EMAIL = "email"
    FILE = "file"


@dataclass
class Insight:
    type: str  # stale, contradiction, connection, orphan, suggestion, pattern, person
    title: str
    description: str
    related_entity_names: list[str] = field(default_factory=list)
    related_item_ids: list[str] = field(default_factory=list)


@dataclass
class EntityMention:
    """A named thing the item talks about. Resolved against existing entities
    by the compiler, which either attaches new facts to an existing entity or
    creates a new one."""
    canonical_name: str
    entity_type: str  # person / project / company / concept / place / event / topic
    aliases: list[str]
    description: str | None
    # Context snippet from the item (~20 words around the mention). Used by the
    # resolver for embedding-based disambiguation.
    context: str | None


@dataclass
class ExtractedFact:
    """An atomic claim drawn from a raw item, linked to one or more entities.
    Facts must ground in the source -- source_quote is preferred and the
    extractor prompt forbids inference from absence."""
    content: str  # one-sentence claim
    fact_type: str  # claim / decision / event / question / preference / definition / attribution
    # Each entry names an entity touched by this fact and its role in the fact:
    # subject / mentioned / attributed_to / location / time.
    # Shape: {"name": str, "type": str, "role": str}
    entity_refs: list[dict]
    fact_time_iso: str | None  # ISO8601 if the fact is about a specific time
    source_quote: str | None
    confidence: float


@dataclass
class RenderedPage:
    """Output of render_entity. `content` is the full markdown page;
    `overview` is a one-paragraph summary for list views. Both use
    `[^<item_id>]` footnote-style citations that must resolve to facts
    supplied as input — the renderer module validates this downstream."""
    content: str
    overview: str
    model_notes: str | None = None


@dataclass
class ProposedRelationship:
    """An engine-proposed semantic edge between two entities found in one
    item. Capable engines emit these directly; BasicEngine's fallback path
    leaves the list empty and lets the compiler infer "related" edges from
    co-occurrence. Names resolve against the same entity list the extractor
    returned, so the compiler can look them up without an extra LLM call."""
    source_name: str
    source_type: str
    target_name: str
    target_type: str
    link_type: str  # related, depends_on, part_of, contradicts, extends, references, etc.
    rationale: str | None = None
    weight: int = 1


@dataclass
class ExtractionResult:
    entities: list[EntityMention]
    facts: list[ExtractedFact]
    relationships: list[ProposedRelationship] = field(default_factory=list)


# --- Multimodal content blocks ---


@dataclass
class TextBlock:
    text: str


@dataclass
class ImageBlock:
    """Raw image bytes + media type. Capable engines pass this to the LLM
    directly; fallback engines should precompute a text description and pass
    that through TextBlock instead."""
    image_bytes: bytes
    media_type: str  # image/png, image/jpeg, image/webp, image/gif


@dataclass
class AudioBlock:
    audio_bytes: bytes
    media_type: str  # audio/mp4, audio/mpeg, audio/wav


ContentBlock = TextBlock | ImageBlock | AudioBlock


@dataclass
class EngineCapabilities:
    """What this engine can do, given its underlying LLMProvider. The compiler
    reads these to pick the shortest path (e.g. hand raw image bytes straight
    to a multimodal engine instead of pre-extracting text)."""
    single_call_extract: bool = False   # extract() uses one rich call
    native_structured_output: bool = False  # tool use or JSON mode guarantees schema
    multimodal: bool = False  # can consume ImageBlock / AudioBlock directly
    emits_relationships: bool = False  # ExtractionResult.relationships will be populated
    inline_rendering: bool = False     # renders entity pages inline (no background pass)


class CompilationEngine(ABC):

    # Engines override this to advertise what they support.
    capabilities: EngineCapabilities = EngineCapabilities()

    @abstractmethod
    async def extract(
        self,
        content: str | list[ContentBlock],
        content_type: ContentType,
        user_notes: str | None = None,
    ) -> ExtractionResult:
        """Extract entities, atomic facts, and semantic relationships from a
        raw item. `content` is either a plain string or a list of
        ContentBlocks; engines whose capabilities declare `multimodal` can
        consume ImageBlock / AudioBlock directly."""
        ...

    async def render_entity(
        self,
        entity: dict,
        facts: list[dict],
        related: list[dict] | None = None,
    ) -> RenderedPage:
        """Render an entity page from its facts.

        `entity` keys: canonical_name, entity_type, aliases, description.
        `facts` is newest-first; each dict has: item_id, content, fact_type,
            source_quote, confidence, created_at, role (on this entity),
            fact_time.
        `related` is optional: [{name, type, link_type, weight}, ...].

        Must use `[^<item_id>]` footnote-style citations. Every cited item_id
        must appear in `facts`. Default raises — entity engines override."""
        raise NotImplementedError("This engine does not support entity rendering")

    async def find_insights(
        self,
        touched_entities: list[dict],
        neighborhood: list[dict],
        recent_facts: list[dict],
    ) -> list[Insight]:
        """Produce insights scoped to the entities touched by an ingest.

        Called after every process_item in entity mode (Phase 4). The compiler
        supplies:
          - touched_entities: entities that received new facts this ingest
          - neighborhood: entities within 2 hops of those, via entity_links
          - recent_facts: facts on any of the above, newest first

        Return typed insights (the seven categories from the product spec:
        stale, contradiction, connection, orphan, suggestion, pattern, person).
        No numeric cap — return as many as the content warrants.

        Default is empty so document-mode engines don't have to implement it.
        """
        return []

    async def consolidate_types(
        self,
        entity_types: list[dict],
        fact_types: list[dict],
        fact_roles: list[dict],
    ) -> dict[str, list[dict]]:
        """Review the free-form type vocabularies the extractor has accrued
        and propose merges (e.g. "individual" -> "person"). The compiler
        applies the result by writing `merged_into` entries on the dim-table
        rows. Returns a dict with keys `entity_types`, `fact_types`,
        `fact_roles`; each value is a list of {from, to, reason} dicts.

        This is the entity-world analogue of evolve_schema. Default is a
        no-op so engines that haven't implemented it stay safe.
        """
        return {"entity_types": [], "fact_types": [], "fact_roles": []}


def content_to_text(content: str | list[ContentBlock]) -> str:
    """Collapse a ContentBlock list to plain text for engines/paths that
    can't handle multimodal. Non-text blocks are represented as a marker
    so callers can decide to warn or fall back to local extraction."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ImageBlock):
            parts.append("[image omitted — engine is not multimodal]")
        elif isinstance(block, AudioBlock):
            parts.append("[audio omitted — engine is not multimodal]")
    return "\n\n".join(parts)
