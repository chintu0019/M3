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
    ) -> Classification:
        ...

    @abstractmethod
    async def compile(
        self,
        classified_item: Classification,
        original_content: str,
        related_pages: list[dict],
        wiki_schema: str,
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
