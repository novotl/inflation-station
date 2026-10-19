"""rename account_id to portfolio_id

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("purchase", "ledger_entry")


def upgrade() -> None:
    # SQLite renames the column in place, unique constraint included, so every stored row keeps its Portfolio.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN account_id TO portfolio_id")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} RENAME COLUMN portfolio_id TO account_id")
