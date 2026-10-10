import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from inflation_station.purchase import Purchase

DATABASE_NAME = "inflation-station.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase (
    platform TEXT NOT NULL,
    account_id TEXT NOT NULL,
    source_row_id TEXT NOT NULL,
    isin TEXT NOT NULL,
    fund_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    units TEXT NOT NULL,
    unit_price TEXT NOT NULL,
    unit_price_currency TEXT NOT NULL,
    gross_czk TEXT NOT NULL,
    fee TEXT NOT NULL,
    fee_currency TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (platform, account_id, source_row_id)
);
"""


@dataclass(frozen=True)
class PurchasesAdded:
    added: int
    already_present: int


class Store:
    """The SQLite database in the data directory. The only place that issues SQL.

    Amounts are stored as decimal text, never as floats.
    """

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / DATABASE_NAME
        with closing(sqlite3.connect(self._path)) as connection:
            connection.executescript(SCHEMA)

    def add_purchases(self, purchases: Iterable[Purchase]) -> PurchasesAdded:
        imported_at = datetime.now(UTC).isoformat()
        added = already_present = 0
        with closing(sqlite3.connect(self._path)) as connection, connection:
            for purchase in purchases:
                row = _purchase_row(purchase) | {"imported_at": imported_at}
                columns = ", ".join(row)
                placeholders = ", ".join(f":{c}" for c in row)
                cursor = connection.execute(
                    f"INSERT INTO purchase ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",  # noqa: S608 - column names are ours
                    row,
                )
                if cursor.rowcount:
                    added += 1
                else:
                    already_present += 1
        return PurchasesAdded(added=added, already_present=already_present)


def _purchase_row(p: Purchase) -> dict[str, str]:
    return {
        "platform": p.platform,
        "account_id": p.account_id,
        "source_row_id": p.source_row_id,
        "isin": p.isin,
        "fund_name": p.fund_name,
        "trade_date": p.trade_date.isoformat(),
        "units": str(p.units),
        "unit_price": str(p.unit_price),
        "unit_price_currency": p.unit_price_currency,
        "gross_czk": str(p.gross_czk),
        "fee": str(p.fee),
        "fee_currency": p.fee_currency,
    }
