"""Canvas layout persistence.

Revision ID: 006
Revises: 005
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canvas_layout",
        sa.Column("node_type", sa.String(30), primary_key=True),
        sa.Column("node_id", sa.String(64), primary_key=True),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("z_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("idx_canvas_layout_node_type", "canvas_layout", ["node_type"])


def downgrade() -> None:
    op.drop_index("idx_canvas_layout_node_type", table_name="canvas_layout")
    op.drop_table("canvas_layout")
