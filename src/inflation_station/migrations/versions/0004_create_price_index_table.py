"""create price_index table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_index",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series", sa.String(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series", "month"),
    )


def downgrade() -> None:
    op.drop_table("price_index")
