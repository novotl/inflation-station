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

PURCHASE_MOVEMENT = "Investice klienta (vklad)"
CASH_DEPOSIT_MOVEMENT = "Vklad - vyrovnání nákupu CP klienta - Vklad pro obchod"

# The columns read from the export, each named once.
MOVEMENT_TYPE = "Typ pohybu"
ROW_ID = "ID pohybu"
ACCOUNT_ID = "Portfolio"
ISIN = "ISIN"
FUND_NAME = "Název CP"
TRADE_DATE = "Datum a čas zobchodování"
UNITS = "Počet ks"
UNIT_PRICE = "Hodnota za ks (v měně obchodu)"
UNIT_PRICE_CURRENCY = "Měna kusové hodnoty (v měně obchodu)"
PAYMENT = "Objem v měně platby"
PAYMENT_CURRENCY = "Měna platby"
FEE = "Poplatek (v měně obchodu)"
FEE_CURRENCY = "Měna poplatku (v měně obchodu)"
COLUMNS = (
    MOVEMENT_TYPE,
    ROW_ID,
    ACCOUNT_ID,
    ISIN,
    FUND_NAME,
    TRADE_DATE,
    UNITS,
    UNIT_PRICE,
    UNIT_PRICE_CURRENCY,
    PAYMENT,
    PAYMENT_CURRENCY,
    FEE,
    FEE_CURRENCY,
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
    if movement_type == CASH_DEPOSIT_MOVEMENT:
        return None
    if movement_type != PURCHASE_MOVEMENT:
        msg = f"unknown movement type {movement_type!r}"
        raise RowError(msg)
    if row[PAYMENT_CURRENCY] != "CZK":
        msg = f"payment currency is {row[PAYMENT_CURRENCY]!r}, expected 'CZK'"
        raise RowError(msg)
    return Purchase(
        platform="jt",
        account_id=row[ACCOUNT_ID],
        source_row_id=row[ROW_ID],
        isin=row[ISIN],
        fund_name=row[FUND_NAME],
        trade_date=_date(row, TRADE_DATE),
        units=_decimal(row, UNITS),
        unit_price=_decimal(row, UNIT_PRICE),
        unit_price_currency=row[UNIT_PRICE_CURRENCY],
        # Paid amounts are negative; the gross amount includes the fee.
        gross_czk=-_decimal(row, PAYMENT),
        fee=_decimal(row, FEE),
        fee_currency=row[FEE_CURRENCY],
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
