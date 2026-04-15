"""Entity-centric wiki foundation.

Revision ID: 003
Revises: 002
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm is used for name-based entity resolution (fast fuzzy match before
    # we fall back to embedding similarity or an LLM disambiguation call).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Entities: canonical pages around people / projects / concepts / etc.
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("canonical_name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("description", sa.Text()),
        sa.Column("embedding", Vector(768)),
        sa.Column("page_content", sa.Text()),
        sa.Column("page_overview", sa.Text()),
        sa.Column("page_dirty", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("facts_since_render", sa.Integer(), server_default="0", nullable=False),
        sa.Column("resolution_method", sa.String(50)),
        sa.Column("resolution_confidence", sa.Float()),
        sa.Column("legacy_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wiki_pages.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("canonical_name", "entity_type", name="uq_entities_name_type"),
    )
    op.create_index("idx_entities_type", "entities", ["entity_type"])
    op.create_index("idx_entities_dirty", "entities", ["page_dirty"], postgresql_where=sa.text("page_dirty"))
    op.execute(
        "CREATE INDEX idx_entities_name_trgm ON entities USING gin (canonical_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX idx_entities_embedding ON entities USING hnsw (embedding vector_cosine_ops)"
    )

    # Facts: atomic claims extracted from raw items, tied to one or more entities.
    op.create_table(
        "entity_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(50), nullable=False),
        sa.Column("fact_time", sa.DateTime(timezone=True)),
        sa.Column("source_quote", sa.Text()),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_entity_facts_item", "entity_facts", ["item_id"])
    op.create_index("idx_entity_facts_type", "entity_facts", ["fact_type"])

    # Entity <-> fact link: many-to-many with a role tag.
    op.create_table(
        "entity_fact_links",
        sa.Column("fact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entity_facts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(30), server_default="subject", nullable=False),
    )
    op.create_index("idx_entity_fact_links_entity", "entity_fact_links", ["entity_id"])

    # Entity graph: derived from fact co-occurrence.
    op.create_table(
        "entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", sa.String(50), server_default="related"),
        sa.Column("weight", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_entity_id", "target_entity_id", "link_type", name="uq_entity_links"),
    )
    op.create_index("idx_entity_links_source", "entity_links", ["source_entity_id"])
    op.create_index("idx_entity_links_target", "entity_links", ["target_entity_id"])

    # Insights: cross-entity patterns, contradictions, suggestions.
    op.create_table(
        "insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("insight_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_entity_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}"),
        sa.Column("related_item_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), server_default="{}"),
        sa.Column("status", sa.String(20), server_default="new", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_insights_status", "insights", ["status"])
    op.create_index("idx_insights_type", "insights", ["insight_type"])

    # Legacy flag on wiki_pages so Phase 6 can sweep without hunting.
    op.add_column(
        "wiki_pages",
        sa.Column("legacy", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("wiki_pages", "legacy")
    op.drop_index("idx_insights_type", table_name="insights")
    op.drop_index("idx_insights_status", table_name="insights")
    op.drop_table("insights")
    op.drop_index("idx_entity_links_target", table_name="entity_links")
    op.drop_index("idx_entity_links_source", table_name="entity_links")
    op.drop_table("entity_links")
    op.drop_index("idx_entity_fact_links_entity", table_name="entity_fact_links")
    op.drop_table("entity_fact_links")
    op.drop_index("idx_entity_facts_type", table_name="entity_facts")
    op.drop_index("idx_entity_facts_item", table_name="entity_facts")
    op.drop_table("entity_facts")
    op.execute("DROP INDEX IF EXISTS idx_entities_embedding")
    op.execute("DROP INDEX IF EXISTS idx_entities_name_trgm")
    op.drop_index("idx_entities_dirty", table_name="entities")
    op.drop_index("idx_entities_type", table_name="entities")
    op.drop_table("entities")
    # We don't drop pg_trgm — harmless to leave, and other migrations may use it.
