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
class AddResult:
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

    def add_purchases(self, purchases: Iterable[Purchase]) -> AddResult:
        imported_at = datetime.now(UTC).isoformat()
        added = already_present = 0
        with closing(sqlite3.connect(self._path)) as connection, connection:
            for p in purchases:
                cursor = connection.execute(
                    "INSERT INTO purchase VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    (
                        p.platform,
                        p.account_id,
                        p.source_row_id,
                        p.isin,
                        p.fund_name,
                        p.trade_date.isoformat(),
                        str(p.units),
                        str(p.unit_price),
                        p.unit_price_currency,
                        str(p.gross_czk),
                        str(p.fee),
                        p.fee_currency,
                        imported_at,
                    ),
                )
                if cursor.rowcount:
                    added += 1
                else:
                    already_present += 1
        return AddResult(added=added, already_present=already_present)
