"""
M3 API Schemas — Pydantic V2 request/response models.
"""

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# --- Ingest ---


class IngestRequest(BaseModel):
    content_text: str | None = None
    content_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    project: str | None = None
    source_channel: str = "api"
    source_metadata: dict = Field(default_factory=dict)


class IngestResponse(BaseModel):
    id: uuid.UUID
    status: str
    message: str


class RawItemResponse(BaseModel):
    id: uuid.UUID
    content_text: str | None
    content_type: str | None
    source_channel: str | None
    source_metadata: dict
    file_path: str | None
    file_url: str | None = None
    user_tags: list[str]
    user_project: str | None
    status: str
    error_message: str | None
    created_at: datetime
    processing_started_at: datetime | None = None
    processed_at: datetime | None


# --- Wiki ---


class WikiPageSummary(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    page_type: str | None
    tags: list[str]
    confidence: float
    created_at: datetime
    updated_at: datetime


class WikiPageResponse(WikiPageSummary):
    content: str
    source_items: list[uuid.UUID]
    metadata: dict
    linked_pages: list["LinkedPageInfo"] = Field(default_factory=list)


class LinkedPageInfo(BaseModel):
    id: uuid.UUID
    title: str
    link_type: str
    direction: str  # "outgoing" or "incoming"


class SearchResultResponse(BaseModel):
    page_id: uuid.UUID
    title: str
    snippet: str
    score: float
    category: str | None


class GraphNode(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    page_type: str | None
    tags: list[str]
    connection_count: int


class GraphEdge(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    link_type: str
    weight: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ChangelogResponse(BaseModel):
    id: uuid.UUID
    action: str | None
    page_id: uuid.UUID | None
    description: str | None
    created_at: datetime


# --- Chat ---


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


# --- Library (detail, notes, bulk, stats) ---


class ItemNoteResponse(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime


class ItemNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class ItemNoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class WikiPageLinkedToItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    page_type: str | None
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    updated_at: datetime


class ItemDetailResponse(RawItemResponse):
    notes: list[ItemNoteResponse] = Field(default_factory=list)
    linked_wiki_pages: list[WikiPageLinkedToItem] = Field(default_factory=list)


class ItemPatchRequest(BaseModel):
    filename: str | None = None
    user_tags: list[str] | None = None
    user_project: str | None = None


class BulkIdsRequest(BaseModel):
    ids: list[uuid.UUID]


class BulkOpError(BaseModel):
    id: str
    error: str


class BulkOpResult(BaseModel):
    succeeded: list[uuid.UUID] = Field(default_factory=list)
    failed: list[BulkOpError] = Field(default_factory=list)


class CountItem(BaseModel):
    key: str
    count: int


class LibraryStatsResponse(BaseModel):
    totals: dict[str, int]  # keys: all, recent, pending, processing, done, error
    projects: list[CountItem]
    types: list[CountItem]
    sources: list[CountItem]


# --- Generic ---


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int


# --- Entities (Phase 3) ---


class EntitySummary(BaseModel):
    id: uuid.UUID
    canonical_name: str
    entity_type: str
    aliases: list[str] = []
    updated_at: datetime
    has_page: bool
    facts_since_render: int


class RelatedEntity(BaseModel):
    id: uuid.UUID
    canonical_name: str
    entity_type: str
    link_type: str
    weight: int


class EntityDetail(BaseModel):
    id: uuid.UUID
    canonical_name: str
    entity_type: str
    aliases: list[str] = []
    description: str | None = None
    page_content: str | None = None
    page_overview: str | None = None
    page_dirty: bool
    facts_since_render: int
    created_at: datetime
    updated_at: datetime
    related: list[RelatedEntity] = []
    insights: list["InsightSummary"] = []


# --- Entity graph (Phase 5) ---


class EntityGraphNode(BaseModel):
    id: uuid.UUID
    canonical_name: str
    entity_type: str
    fact_count: int


class EntityGraphEdge(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    link_type: str
    weight: int


class EntityGraphResponse(BaseModel):
    nodes: list[EntityGraphNode]
    edges: list[EntityGraphEdge]


# --- Insights (Phase 4) ---


class InsightSummary(BaseModel):
    id: uuid.UUID
    insight_type: str
    title: str
    description: str
    related_entity_ids: list[uuid.UUID] = []
    related_item_ids: list[uuid.UUID] = []
    status: str
    created_at: datetime


class InsightPatchRequest(BaseModel):
    status: str  # new | acknowledged | dismissed
