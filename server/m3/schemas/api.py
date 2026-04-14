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


# --- Generic ---


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
