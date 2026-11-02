"""link each Fee charged on a Purchase to its Holding's Fund

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("fee") as batch:
        batch.add_column(sa.Column("fund_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_fee_fund_id_fund", "fund", ["fund_id"], ["id"])
    # A Fee charged on a Purchase has its Purchase's source row (J&T Banka, INVESTIKA); no other Fee (Portu) has one.
    op.execute(
        "UPDATE fee SET fund_id = ("
        "SELECT purchase.fund_id FROM purchase"
        " WHERE purchase.portfolio_id = fee.portfolio_id AND purchase.source_row_id = fee.source_row_id"
        ")"
    )


def downgrade() -> None:
    with op.batch_alter_table("fee") as batch:
        batch.drop_constraint("fk_fee_fund_id_fund", type_="foreignkey")
        batch.drop_column("fund_id")
