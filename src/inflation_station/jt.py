"""Reads J&T Banka transaction exports: semicolons, Czech headers, `"1 501,01"` numbers, `HH:MM DD.MM.YYYY` dates."""

import csv
from datetime import date, datetime
from typing import TYPE_CHECKING

from inflation_station import czech, fee
from inflation_station.errors import InflationStationError
from inflation_station.purchase import Purchase

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path

    from inflation_station.fee import Fee

PURCHASE_MOVEMENT = "Investice klienta (vklad)"
CASH_DEPOSIT_PREFIX = "Vklad"

# The columns read from the export, each named once.
MOVEMENT_TYPE = "Typ pohybu"
ROW_ID = "ID pohybu"
PORTFOLIO_ID = "Portfolio"
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
    PORTFOLIO_ID,
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


class RowError(Exception):
    """A problem with one row; read_export adds which file and row."""


def read_export(path: Path) -> tuple[list[Purchase], list[Fee]]:
    """Return the Purchases in a J&T export and the Fees charged on them.

    Raises on anything it doesn't understand, so nothing is half-read.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a J&T export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            purchases: list[Purchase] = []
            fees: list[Fee] = []
            for row in reader:
                try:
                    bought = _purchase(row)
                except RowError as e:
                    msg = f"{path.name} row {reader.line_num} ({ROW_ID} {row[ROW_ID]}): {e}"
                    raise InflationStationError(msg) from e
                if bought:
                    purchases.append(bought[0])
                    fees.extend(bought[1])
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    return purchases, fees


def _purchase(row: dict[str, str]) -> tuple[Purchase, list[Fee]] | None:
    movement_type = row[MOVEMENT_TYPE]
    if _is_cash_deposit(row):
        return None
    if movement_type != PURCHASE_MOVEMENT:
        msg = f"unknown movement type {movement_type!r}"
        raise RowError(msg)
    if row[PAYMENT_CURRENCY] != "CZK":
        msg = f"payment currency is {row[PAYMENT_CURRENCY]!r}, expected 'CZK'"
        raise RowError(msg)
    if row[FEE_CURRENCY] != "CZK":
        msg = f"fee currency is {row[FEE_CURRENCY]!r}, expected 'CZK'"
        raise RowError(msg)
    # Paid amounts are negative, and include the fee.
    paid = -_decimal(row, PAYMENT)
    fee_czk = _decimal(row, FEE)
    purchase = Purchase(
        platform="jt",
        portfolio_id=row[PORTFOLIO_ID],
        source_row_id=row[ROW_ID],
        isin=row[ISIN],
        fund_name=row[FUND_NAME],
        trade_date=_date(row, TRADE_DATE),
        units=_decimal(row, UNITS),
        unit_price=_decimal(row, UNIT_PRICE),
        unit_price_currency=row[UNIT_PRICE_CURRENCY],
        czk=paid - fee_czk,
    )
    return purchase, fee.charged_on(purchase, fee_czk)


def _is_cash_deposit(row: dict[str, str]) -> bool:
    """A "Vklad…" movement with no ISIN. J&T keeps renaming these ("Vklad klienta - <n>", …), so match by shape."""
    return row[MOVEMENT_TYPE].startswith(CASH_DEPOSIT_PREFIX) and not row[ISIN]


def _date(row: dict[str, str], column: str) -> date:
    try:
        return datetime.strptime(row[column], "%H:%M %d.%m.%Y").date()  # noqa: DTZ007 - the export's dates are naive
    except ValueError as e:
        msg = f"{column} {row[column]!r} is not a date like '00:00 31.12.2021'"
        raise RowError(msg) from e


def _decimal(row: dict[str, str], column: str) -> Decimal:
    number = czech.decimal(row[column])
    if number is None:
        msg = f"{column} {row[column]!r} is not a number like '1 501,01'"
        raise RowError(msg)
    return number
