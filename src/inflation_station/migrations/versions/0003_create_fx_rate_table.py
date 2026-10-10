"""create fx_rate table

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("czk_per_unit", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("currency", "day"),
    )


def downgrade() -> None:
    op.drop_table("fx_rate")
