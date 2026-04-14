"""Initial schema -- all core tables and indexes.

Revision ID: 001
Revises: None
Create Date: 2026-04-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "raw_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_type", sa.String(50)),
        sa.Column("source_channel", sa.String(50)),
        sa.Column("source_metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("file_path", sa.String(500)),
        sa.Column("user_tags", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("user_project", sa.String(200)),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_raw_items_status", "raw_items", ["status"])

    op.create_table(
        "wiki_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(200)),
        sa.Column("page_type", sa.String(100)),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("embedding", Vector(768)),
        sa.Column("source_items", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE INDEX idx_wiki_pages_fts ON wiki_pages "
        "USING gin(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, '')))"
    )
    op.execute(
        "CREATE INDEX idx_wiki_pages_embedding ON wiki_pages "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index("idx_wiki_pages_tags", "wiki_pages", ["tags"], postgresql_using="gin")
    op.create_index("idx_wiki_pages_category", "wiki_pages", ["category"])

    op.create_table(
        "wiki_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wiki_pages.id", ondelete="CASCADE")),
        sa.Column("target_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wiki_pages.id", ondelete="CASCADE")),
        sa.Column("link_type", sa.String(50), server_default="references"),
        sa.Column("weight", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_page_id", "target_page_id", "link_type"),
    )

    op.create_table(
        "wiki_schema",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "changelog",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("action", sa.String(50)),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wiki_pages.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("changelog")
    op.drop_table("wiki_schema")
    op.drop_table("wiki_links")
    op.drop_table("wiki_pages")
    op.drop_table("raw_items")
    op.execute("DROP EXTENSION IF EXISTS vector")
