"""Reads J&T Banka transaction exports: semicolons, Czech headers, `"1 501,01"` numbers, `HH:MM DD.MM.YYYY` dates."""

import csv
from datetime import date, datetime
from typing import TYPE_CHECKING

from inflation_station import czech
from inflation_station.currency import code as currency_code
from inflation_station.domain import CONVERSION_SUFFIX, Conversion, Fee, Fund, Platform, Portfolio, Purchase, Rows
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path

CZK = "CZK"
PURCHASE_MOVEMENT = "Investice klienta (vklad)"
CASH_DEPOSIT_PREFIX = "Vklad"

# The columns read from the export, each named once.
MOVEMENT_TYPE = "Typ pohybu"
ROW_ID = "ID pohybu"
PORTFOLIO = "Portfolio"
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
VOLUME = "Objem (v měně obchodu)"
VOLUME_CURRENCY = "Měna objemu obchodu (v měně obchodu)"
COLUMNS = (
    MOVEMENT_TYPE,
    ROW_ID,
    PORTFOLIO,
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
    VOLUME,
    VOLUME_CURRENCY,
)


class RowError(Exception):
    """A problem with one row; read_export adds which file and row."""


def read_export(path: Path) -> Rows:
    """Return the Purchases in a J&T export, the Fees charged on them, and the Conversions of what paid for those not
    priced in CZK.

    Raises on anything it doesn't understand, so nothing is half-read.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a J&T export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            rows = Rows()
            for row in reader:
                try:
                    rows += _purchase(row)
                except RowError as e:
                    msg = f"{path.name} row {reader.line_num} ({ROW_ID} {row[ROW_ID]}): {e}"
                    raise InflationStationError(msg) from e
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    return rows


def _purchase(row: dict[str, str]) -> Rows:
    """The Purchase in a row, its Fee unless that is zero, and the Conversion paying for it unless it is priced in CZK.

    None of them for a cash deposit.
    """
    movement_type = row[MOVEMENT_TYPE]
    if _is_cash_deposit(row):
        return Rows()
    if movement_type != PURCHASE_MOVEMENT:
        msg = f"unknown movement type {movement_type!r}"
        raise RowError(msg)
    if row[PAYMENT_CURRENCY] != CZK:
        msg = f"payment currency is {row[PAYMENT_CURRENCY]!r}, expected {CZK!r}"
        raise RowError(msg)
    # Paid amounts are negative, and include the fee.
    paid = -_decimal(row, PAYMENT)
    fee = _decimal(row, FEE)
    if fee and row[FEE_CURRENCY] != CZK:
        msg = f"fee currency is {row[FEE_CURRENCY]!r}, expected {CZK!r}"
        raise RowError(msg)
    currency = _currency(row, UNIT_PRICE_CURRENCY)
    portfolio = Portfolio(Platform.JT, key=row[PORTFOLIO], name=row[PORTFOLIO])
    day = _date(row, TRADE_DATE)
    rows = Rows(fees=[Fee(portfolio, row[ROW_ID], day, fee, CZK)] if fee else [])
    # What bought the units, in CZK.
    amount = paid - fee
    if currency != CZK:
        # J&T changes the CZK into the units' currency itself; the volume is what it got.
        if _currency(row, VOLUME_CURRENCY) != currency:
            msg = f"{VOLUME_CURRENCY} is {row[VOLUME_CURRENCY]!r}, expected {currency!r} like {UNIT_PRICE_CURRENCY}"
            raise RowError(msg)
        bought = _decimal(row, VOLUME)
        rows += Rows(
            conversions=[Conversion(portfolio, row[ROW_ID] + CONVERSION_SUFFIX, day, amount, CZK, bought, currency)]
        )
        amount = bought
    purchase = Purchase(
        portfolio=portfolio,
        fund=Fund(row[ISIN], row[FUND_NAME]),
        source_row_id=row[ROW_ID],
        day=day,
        units=_decimal(row, UNITS),
        unit_price=_decimal(row, UNIT_PRICE),
        currency=currency,
        amount=amount,
    )
    return rows + Rows(purchases=[purchase])


def _currency(row: dict[str, str], column: str) -> str:
    try:
        return currency_code(row[column])
    except ValueError as e:
        msg = f"{column} {e}"
        raise RowError(msg) from e


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
