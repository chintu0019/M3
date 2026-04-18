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


# --- Chat ---


class ChatRequest(BaseModel):
    message: str
    thread_id: uuid.UUID | None = None
    conversation_id: str | None = None  # retained for backward compat; unused


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


class ItemDetailResponse(RawItemResponse):
    notes: list[ItemNoteResponse] = Field(default_factory=list)


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


# --- Canvas ---


class CanvasNode(BaseModel):
    id: str  # "entity:<uuid>" or "insight:<uuid>"
    node_type: str  # "entity" | "insight"
    label: str
    data: dict  # type-specific payload (entity_type, has_page, insight_type, etc.)
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


class CanvasEdge(BaseModel):
    id: str  # "link:<uuid>"
    source: str  # node id
    target: str  # node id
    edge_type: str  # "related", "references", etc.
    weight: float = 1.0


class CanvasResponse(BaseModel):
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]


class CanvasLayoutUpdate(BaseModel):
    node_type: str
    node_id: str
    x: float
    y: float
    width: float | None = None
    height: float | None = None
    z_index: int = 0


class CanvasLayoutBulkRequest(BaseModel):
    updates: list[CanvasLayoutUpdate]


class CanvasLayoutBulkResponse(BaseModel):
    written: int


# --- Entity write operations (Phase B) ---


class EntityCreateRequest(BaseModel):
    canonical_name: str = Field(..., min_length=1, max_length=500)
    entity_type: str = Field(..., min_length=1, max_length=50)
    description: str | None = None


class EntityPatchRequest(BaseModel):
    canonical_name: str | None = Field(None, min_length=1, max_length=500)
    page_content: str | None = None  # pass "" to clear, None to leave unchanged
    description: str | None = None


class EntityLinkCreateRequest(BaseModel):
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    link_type: str = Field("related", min_length=1, max_length=50)
    weight: int = Field(1, ge=1, le=10)


class EntityLinkResponse(BaseModel):
    id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    link_type: str
    weight: int


# --- Chat threads (Phase C) ---


class ChatThreadCreateRequest(BaseModel):
    title: str | None = None


class ChatThreadSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    summary: str | None
    status: str
    created_at: datetime
    ended_at: datetime | None
    crystallized_at: datetime | None = None
    message_count: int


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class ChatThreadDetail(ChatThreadSummary):
    messages: list[ChatMessageResponse]
    cited_entity_ids: list[uuid.UUID]


# --- Crystallization (Phase D) ---


class ThreadCrystallizeResponse(BaseModel):
    thread_id: uuid.UUID
    raw_item_id: uuid.UUID
    enqueued: bool


class SelfContextSettings(BaseModel):
    enabled: bool


class ThemeSetting(BaseModel):
    theme: str  # "document" | "notebook" | "observatory"
