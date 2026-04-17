"""Drop document-pipeline tables (Phase 7 cleanup).

Phase 6 flipped the default wiki_mode to "entity" and the entity pipeline has
been the only writer since. This migration removes the now-dead document
tables — wiki_pages, wiki_links, wiki_schema, changelog — along with
entities.legacy_page_id, which pointed at wiki_pages for a backfill cross-ref
that is no longer needed.

The drop order matters:
  1. entities.legacy_page_id FK -> wiki_pages
  2. changelog.page_id FK -> wiki_pages
  3. wiki_links (FKs to wiki_pages)
  4. wiki_pages
  5. wiki_schema, changelog

Revision ID: 005
Revises: 004
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Remove the FK column on entities that pointed at wiki_pages.
    op.drop_column("entities", "legacy_page_id")

    # 2. changelog has an FK to wiki_pages — drop the whole table.
    op.drop_table("changelog")

    # 3. wiki_links references wiki_pages on both sides.
    op.drop_table("wiki_links")

    # 4. wiki_pages itself, plus its indexes (Postgres drops them with the
    # table but being explicit about extensions-heavy ones is friendlier
    # to other environments).
    op.drop_index("idx_wiki_pages_embedding", table_name="wiki_pages", if_exists=True)
    op.drop_index("idx_wiki_pages_fts", table_name="wiki_pages", if_exists=True)
    op.drop_index("idx_wiki_pages_category", table_name="wiki_pages", if_exists=True)
    op.drop_index("idx_wiki_pages_tags", table_name="wiki_pages", if_exists=True)
    op.drop_table("wiki_pages")

    # 5. wiki_schema — standalone.
    op.drop_table("wiki_schema")


def downgrade() -> None:
    # Recreate the minimal shape so an upgrade rollback doesn't hang; the
    # data is not restored. This is best-effort: document-pipeline code is
    # gone, so a real rollback requires restoring the pre-005 code too.
    op.create_table(
        "wiki_schema",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "wiki_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(200)),
        sa.Column("page_type", sa.String(100)),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("embedding", sa.dialects.postgresql.BYTEA()),  # placeholder
        sa.Column(
            "source_items",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
        ),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("legacy", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.create_table(
        "wiki_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "target_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        ),
        sa.Column("link_type", sa.String(50), server_default="references"),
        sa.Column("weight", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_page_id", "target_page_id", "link_type"),
    )

    op.create_table(
        "changelog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action", sa.String(50)),
        sa.Column(
            "page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wiki_pages.id", ondelete="SET NULL"),
        ),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "entities",
        sa.Column(
            "legacy_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wiki_pages.id", ondelete="SET NULL"),
        ),
    )
