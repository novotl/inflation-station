"""Reads J&T Banka transaction exports: semicolons, Czech headers, `"1 501,01"` numbers, `HH:MM DD.MM.YYYY` dates."""

import csv
import re
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station.errors import InflationStationError
from inflation_station.purchase import Purchase

if TYPE_CHECKING:
    from pathlib import Path

PURCHASE = "Investice klienta (vklad)"
CASH_DEPOSIT = "Vklad - vyrovnání nákupu CP klienta - Vklad pro obchod"

MOVEMENT_TYPE = "Typ pohybu"
ROW_ID = "ID pohybu"
COLUMNS = (
    MOVEMENT_TYPE,
    ROW_ID,
    "Účet",
    "ISIN",
    "Název CP",
    "Datum a čas zobchodování",
    "Počet ks",
    "Hodnota za ks (v měně obchodu)",
    "Měna kusové hodnoty (v měně obchodu)",
    "Objem v měně platby",
    "Měna platby",
    "Poplatek (v měně obchodu)",
    "Měna poplatku (v měně obchodu)",
)

# Thousands separators may be a plain, no-break or narrow no-break space.
_SPACES = re.compile(r"[ \u00a0\u202f]")
_NUMBER = re.compile(r"-?(\d+(\.\d*)?|\.\d+)")


class RowError(Exception):
    """A problem with one row; read_export adds which file and row."""


def read_export(path: Path) -> list[Purchase]:
    """Return the Purchases in a J&T export. Raises on anything it doesn't understand, so nothing is half-read."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a J&T export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            purchases = []
            for row in reader:
                try:
                    purchase = _purchase(row)
                except RowError as e:
                    msg = f"{path.name} row {reader.line_num} ({ROW_ID} {row[ROW_ID]}): {e}"
                    raise InflationStationError(msg) from e
                if purchase:
                    purchases.append(purchase)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    return purchases


def _purchase(row: dict[str, str]) -> Purchase | None:
    movement_type = row[MOVEMENT_TYPE]
    if movement_type == CASH_DEPOSIT:
        return None
    if movement_type != PURCHASE:
        msg = f"unknown movement type {movement_type!r}"
        raise RowError(msg)
    if row["Měna platby"] != "CZK":
        msg = f"payment currency is {row['Měna platby']!r}, expected 'CZK'"
        raise RowError(msg)
    return Purchase(
        platform="jt",
        account_id=row["Účet"],
        source_row_id=row[ROW_ID],
        isin=row["ISIN"],
        fund_name=row["Název CP"],
        trade_date=_date(row, "Datum a čas zobchodování"),
        units=_decimal(row, "Počet ks"),
        unit_price=_decimal(row, "Hodnota za ks (v měně obchodu)"),
        unit_price_currency=row["Měna kusové hodnoty (v měně obchodu)"],
        # Paid amounts are negative; the gross amount includes the fee.
        gross_czk=-_decimal(row, "Objem v měně platby"),
        fee=_decimal(row, "Poplatek (v měně obchodu)"),
        fee_currency=row["Měna poplatku (v měně obchodu)"],
    )


def _date(row: dict[str, str], column: str) -> date:
    try:
        return datetime.strptime(row[column], "%H:%M %d.%m.%Y").date()  # noqa: DTZ007 - the export's dates are naive
    except ValueError as e:
        msg = f"{column} {row[column]!r} is not a date like '00:00 31.12.2021'"
        raise RowError(msg) from e


def _decimal(row: dict[str, str], column: str) -> Decimal:
    text = _SPACES.sub("", row[column]).replace(",", ".")
    if not _NUMBER.fullmatch(text):
        msg = f"{column} {row[column]!r} is not a number like '1 501,01'"
        raise RowError(msg)
    return Decimal(text)
