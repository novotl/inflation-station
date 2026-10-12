"""create ledger_entry table

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("source_row_id", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(), nullable=False),
        sa.Column("units", sa.String(), nullable=False),
        sa.Column("unit_price", sa.String(), nullable=True),
        sa.Column("amount", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "account_id", "source_row_id"),
    )


def downgrade() -> None:
    op.drop_table("ledger_entry")
