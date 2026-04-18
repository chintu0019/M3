"""Seed self-knowledge entities (preferences/context/goals/people).

Revision ID: 008
Revises: 007
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEEDS = [
    ("preferences", "How the user likes things — tools, formats, defaults."),
    ("context", "The user's current situation — projects, locations, constraints."),
    ("goals", "What the user is working toward — short and long term."),
    ("people", "Who the user knows and cares about, with how they're connected."),
]


def upgrade() -> None:
    # Idempotent insert. The unique (canonical_name, entity_type) constraint
    # already covers the seed; ON CONFLICT DO NOTHING keeps re-runs safe.
    op.execute(
        sa.text(
            """
            INSERT INTO entity_types (name, usage_count, description)
            VALUES ('self', 0, 'Reserved type for self-knowledge entities')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )
    for name, desc in SEEDS:
        op.execute(
            sa.text(
                """
                INSERT INTO entities (canonical_name, entity_type, description)
                VALUES (:name, 'self', :desc)
                ON CONFLICT (canonical_name, entity_type) DO NOTHING
                """
            ).bindparams(name=name, desc=desc)
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM entities WHERE entity_type = 'self' AND canonical_name IN ('preferences', 'context', 'goals', 'people')"
        )
    )
    op.execute(sa.text("DELETE FROM entity_types WHERE name = 'self'"))
