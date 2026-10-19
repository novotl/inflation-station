"""split fees out of purchases

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every stored Purchase goes: its gross CZK still holds its fee, and a re-import would keep it as already present
    # while adding the fee as a Fee, counting the fee twice. Re-importing stores the Purchases and their Fees together.
    op.drop_table("purchase")
    _create_purchase_table(sa.Column("czk", sa.String(), nullable=False))


def downgrade() -> None:
    op.drop_table("purchase")
    _create_purchase_table(
        sa.Column("gross_czk", sa.String(), nullable=False),
        sa.Column("fee", sa.String(), nullable=False),
        sa.Column("fee_currency", sa.String(), nullable=False),
    )


def _create_purchase_table(*amount_columns: sa.Column) -> None:
    op.create_table(
        "purchase",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("portfolio_id", sa.String(), nullable=False),
        sa.Column("source_row_id", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("units", sa.String(), nullable=False),
        sa.Column("unit_price", sa.String(), nullable=False),
        sa.Column("unit_price_currency", sa.String(), nullable=False),
        *amount_columns,
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "portfolio_id", "source_row_id"),
    )
