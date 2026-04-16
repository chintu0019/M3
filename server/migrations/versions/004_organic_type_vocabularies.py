"""Organic type vocabularies for entities / facts / roles.

The Phase-2 plan originally hardcoded entity_type, fact_type, and role to
small whitelists. That contradicts the product spec's "no prescribed
structure" philosophy — the LLM should discover categories the same way it
discovers wiki structure, and a background consolidation pass merges near-
duplicates later. Migration 003 already stored these as free-text String
columns (no CHECK constraints), so this migration only needs to add three
small dimension tables that track what types have actually appeared, with
usage counts and a `merged_into` pointer for consolidation output.

Revision ID: 004
Revises: 003
Create Date: 2026-04-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("entity_types", "fact_types", "fact_roles"):
        op.create_table(
            table,
            sa.Column("name", sa.String(100), primary_key=True),
            sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("parent_type", sa.String(100)),
            # merged_into points at a canonical type name when consolidate_types
            # decides this one is a duplicate. The extractor and compiler should
            # dereference on read so callers see the canonical name.
            sa.Column("merged_into", sa.String(100)),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        )
        op.create_index(f"idx_{table}_merged_into", table, ["merged_into"])

    # Seed with the suggested vocabulary so existing prompts remain coherent
    # with what the DB reports. These are suggestions, not constraints —
    # the extractor is free to create new rows on the fly.
    op.execute(
        """
        INSERT INTO entity_types (name, usage_count) VALUES
          ('person', 0), ('project', 0), ('company', 0),
          ('concept', 0), ('place', 0), ('event', 0), ('topic', 0)
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO fact_types (name, usage_count) VALUES
          ('claim', 0), ('decision', 0), ('event', 0), ('question', 0),
          ('preference', 0), ('definition', 0), ('attribution', 0)
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO fact_roles (name, usage_count) VALUES
          ('subject', 0), ('mentioned', 0), ('attributed_to', 0),
          ('location', 0), ('time', 0)
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in ("entity_types", "fact_types", "fact_roles"):
        op.drop_index(f"idx_{table}_merged_into", table_name=table)
        op.drop_table(table)
