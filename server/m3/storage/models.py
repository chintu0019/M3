"""
M3 Database Models — SQLAlchemy 2.0 declarative ORM.

Tables: raw_items, wiki_pages, wiki_links, wiki_schema, changelog.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RawItem(Base):
    __tablename__ = "raw_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    content_text: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(50))
    source_channel: Mapped[str | None] = mapped_column(String(50))
    source_metadata: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    file_path: Mapped[str | None] = mapped_column(String(500))
    user_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    user_project: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(200))
    page_type: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    confidence: Mapped[float] = mapped_column(Float, server_default="0.5")
    embedding = mapped_column(Vector(768), nullable=True)
    source_items: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}"
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    outgoing_links: Mapped[list["WikiLink"]] = relationship(
        back_populates="source_page", foreign_keys="WikiLink.source_page_id"
    )
    incoming_links: Mapped[list["WikiLink"]] = relationship(
        back_populates="target_page", foreign_keys="WikiLink.target_page_id"
    )


class WikiLink(Base):
    __tablename__ = "wiki_links"
    __table_args__ = (
        UniqueConstraint("source_page_id", "target_page_id", "link_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="CASCADE")
    )
    target_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="CASCADE")
    )
    link_type: Mapped[str] = mapped_column(String(50), server_default="references")
    weight: Mapped[float] = mapped_column(Float, server_default="1.0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source_page: Mapped[WikiPage] = relationship(
        back_populates="outgoing_links", foreign_keys=[source_page_id]
    )
    target_page: Mapped[WikiPage] = relationship(
        back_populates="incoming_links", foreign_keys=[target_page_id]
    )


class WikiSchema(Base):
    __tablename__ = "wiki_schema"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Changelog(Base):
    __tablename__ = "changelog"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    action: Mapped[str | None] = mapped_column(String(50))
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
