"""
M3 Compilation Engine — Base Interface

This is the abstraction that separates what's open-source from what's private.
The BasicEngine ships with M3 and works fine.
Custom engines can be loaded via config.yml engine_path.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


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
class Classification:
    summary: str
    tags: list[str]
    project: str | None
    content_type: str
    entities: list[dict]
    confidence: float


@dataclass
class PageUpdate:
    page_id: str | None  # None = create new
    title: str
    content: str
    category: str | None
    page_type: str
    tags: list[str]
    confidence: float


@dataclass
class LinkUpdate:
    source_title: str
    target_title: str
    link_type: str  # references, contradicts, extends, related
    weight: float = 1.0


@dataclass
class CompileResult:
    pages: list[PageUpdate]
    links: list[LinkUpdate]
    schema_updates: str | None
    changelog_entry: str


@dataclass
class Insight:
    type: str  # stale, contradiction, connection, orphan, suggestion, pattern
    title: str
    description: str
    related_pages: list[str]


@dataclass
class SynthesisResult:
    new_links: list[LinkUpdate]
    insights: list[Insight]
    schema_updates: str | None
    changelog_entries: list[str]


# --- Entity-centric wiki (Phase 2+) ---


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
class ExtractionResult:
    entities: list[EntityMention]
    facts: list[ExtractedFact]


class CompilationEngine(ABC):

    @abstractmethod
    async def classify(
        self,
        content: str,
        content_type: ContentType,
        wiki_index: str,
        wiki_schema: str,
        existing_tags: list[str],
        existing_projects: list[str],
        user_tags: list[str] | None = None,
        user_project: str | None = None,
        user_notes: str | None = None,
    ) -> Classification:
        ...

    @abstractmethod
    async def compile(
        self,
        classified_item: Classification,
        original_content: str,
        related_pages: list[dict],
        wiki_schema: str,
        user_notes: str | None = None,
    ) -> CompileResult:
        ...

    @abstractmethod
    async def synthesize(
        self,
        wiki_index: str,
        wiki_schema: str,
        recent_changes: list[str],
        all_page_summaries: list[dict],
    ) -> SynthesisResult:
        ...

    async def extract(
        self,
        content: str,
        content_type: ContentType,
        user_notes: str | None = None,
    ) -> ExtractionResult:
        """
        Extract entities and atomic facts from a raw item. Used by the
        entity-centric wiki pipeline (Phase 2+).

        Deliberately NOT @abstractmethod: engines that don't support
        entity extraction inherit this default and raise at call time
        only if the compiler actually tries to use them in entity mode.
        The compiler checks processing.wiki_mode before calling this,
        so document-mode engines keep working unchanged.
        """
        raise NotImplementedError("This engine does not support entity extraction")
