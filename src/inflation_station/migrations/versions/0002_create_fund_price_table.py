"""create fund_price table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10 13:29:47.646700
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fund_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", "day"),
    )


def downgrade() -> None:
    op.drop_table("fund_price")
