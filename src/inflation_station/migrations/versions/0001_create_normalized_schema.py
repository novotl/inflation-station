"""create the normalized schema

Revision ID: 0001
Revises:
Create Date: 2026-10-19 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The Platform enum's values; spelled out so the migration never changes with the code.
PLATFORMS = ("jt", "investika", "portu")


def upgrade() -> None:
    platform = op.create_table(
        "platform",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.bulk_insert(platform, [{"code": code} for code in PLATFORMS])
    op.create_table(
        "portfolio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["platform_id"], ["platform.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_id", "key"),
    )
    op.create_table(
        "fund",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isin", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin"),
    )
    _create_imported_table("deposit", *_amount("amount", "currency"))
    for trade in ("purchase", "sale"):
        _create_imported_table(
            trade,
            sa.Column("fund_id", sa.Integer(), nullable=False),
            sa.Column("units", sa.String(), nullable=False),
            sa.Column("unit_price", sa.String(), nullable=False),
            *_amount("amount", "currency"),
            sa.ForeignKeyConstraint(["fund_id"], ["fund.id"]),
        )
    _create_imported_table("fee", *_amount("amount", "currency"))
    _create_imported_table("conversion", *_amount("from_amount", "from_currency"), *_amount("to_amount", "to_currency"))
    op.create_table(
        "fund_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        _currency_check("currency"),
        sa.ForeignKeyConstraint(["fund_id"], ["fund.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_id", "day"),
    )
    op.create_table(
        "fx_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *_amount("from_amount", "from_currency"),
        *_amount("to_amount", "to_currency"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "from_currency", "to_currency"),
    )
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
    for table in (
        "price_index",
        "fx_rate",
        "fund_price",
        "conversion",
        "fee",
        "sale",
        "purchase",
        "deposit",
        "fund",
        "portfolio",
        "platform",
    ):
        op.drop_table(table)


def _create_imported_table(name: str, *columns: sa.Column | sa.Constraint) -> None:
    """A table of imported rows: each in a Portfolio, identified within it by its source row."""
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("source_row_id", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *columns,
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "source_row_id"),
    )


def _amount(amount: str, currency: str) -> tuple[sa.Column, sa.Column, sa.CheckConstraint]:
    """An amount column, as decimal text, and the column of its currency."""
    return (
        sa.Column(amount, sa.String(), nullable=False),
        sa.Column(currency, sa.String(), nullable=False),
        _currency_check(currency),
    )


def _currency_check(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} GLOB '[A-Z][A-Z][A-Z]'", name=f"{column}_is_three_capitals")
