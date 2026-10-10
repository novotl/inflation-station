"""create purchase table

Revision ID: 0001
Revises:
Create Date: 2026-10-10 12:03:30.280368
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("source_row_id", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("units", sa.String(), nullable=False),
        sa.Column("unit_price", sa.String(), nullable=False),
        sa.Column("unit_price_currency", sa.String(), nullable=False),
        sa.Column("gross_czk", sa.String(), nullable=False),
        sa.Column("fee", sa.String(), nullable=False),
        sa.Column("fee_currency", sa.String(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "account_id", "source_row_id"),
    )


def downgrade() -> None:
    op.drop_table("purchase")
