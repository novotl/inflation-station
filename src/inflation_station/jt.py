"""Reads J&T Banka transaction exports: semicolons, Czech headers, `"1 501,01"` numbers, `HH:MM DD.MM.YYYY` dates."""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from inflation_station import czech
from inflation_station.currency import CZK
from inflation_station.currency import code as currency_code
from inflation_station.domain import (
    CONVERSION_SUFFIX,
    Conversion,
    Deposit,
    Fee,
    Fund,
    Platform,
    Portfolio,
    Purchase,
    Rows,
)
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path

PURCHASE_MOVEMENT = "Investice klienta (vklad)"
CASH_DEPOSIT_PREFIX = "Vklad"

# The columns read from the export, each named once.
MOVEMENT_TYPE = "Typ pohybu"
ROW_ID = "ID pohybu"
MOVED_DATE = "Datum a čas pohybu"
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
    MOVED_DATE,
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


# How far a Deposit's day may be from the trade day of the Purchase it paid for, either way: J&T used to settle a
# Purchase with a Deposit a few days after the trade ("Vklad - vyrovnání nákupu CP…"), and now takes the Deposit
# a few days before it ("Vklad klienta - …").
PAIRING_WINDOW = timedelta(days=7)


class RowError(Exception):
    """A problem with one row; read_export adds which file and row."""


@dataclass(frozen=True)
class _PurchaseRow:
    """A Purchase row: what it imports as, and the CZK paid for it, Fee included, from which J&T portfolio."""

    rows: Rows
    purchase: Purchase
    jt_portfolio: str
    paid: Decimal


@dataclass(frozen=True)
class _CashDeposit:
    """A Deposit row, waiting to be paired with the Purchase it paid for. `where` names its row in errors."""

    where: str
    jt_portfolio: str
    source_row_id: str
    day: date
    amount: Decimal


def read_export(path: Path) -> Rows:
    """Return the Purchases in a J&T export, the Fees charged on them, the Conversions of what paid for those not
    priced in CZK, and the Deposits paying for them, each in its Purchase's Portfolio.

    Raises on anything it doesn't understand, so nothing is half-read.
    """
    purchase_rows: list[_PurchaseRow] = []
    deposits: list[_CashDeposit] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a J&T export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            for row in reader:
                where = f"{path.name} row {reader.line_num} ({ROW_ID} {row[ROW_ID]})"
                try:
                    if _is_cash_deposit(row):
                        deposits.append(_cash_deposit(row, where))
                    else:
                        purchase_rows.append(_purchase(row))
                except RowError as e:
                    msg = f"{where}: {e}"
                    raise InflationStationError(msg) from e
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    rows = Rows(deposits=_paired(deposits, purchase_rows))
    for b in purchase_rows:
        rows += b.rows
    return rows


def _paired(deposits: list[_CashDeposit], purchase_rows: list[_PurchaseRow]) -> list[Deposit]:
    """Each Deposit, in the Portfolio of the first Purchase not yet paired whose payment, Fee included, it equals, from
    the same J&T portfolio and traded within PAIRING_WINDOW of it. Raises on a Deposit with no such Purchase.
    """
    unpaired = sorted(purchase_rows, key=lambda b: (b.purchase.day, b.purchase.source_row_id))
    paired = []
    for d in sorted(deposits, key=lambda d: (d.day, d.source_row_id)):
        b = next(
            (
                b
                for b in unpaired
                if (b.jt_portfolio, b.paid) == (d.jt_portfolio, d.amount)
                and abs(b.purchase.day - d.day) <= PAIRING_WINDOW
            ),
            None,
        )
        if b is None:
            msg = (
                f"{d.where}: no Purchase paid {d.amount} {CZK} in J&T portfolio {d.jt_portfolio} "
                f"within {PAIRING_WINDOW.days} days of this Deposit, so its Portfolio is unknown"
            )
            raise InflationStationError(msg)
        unpaired.remove(b)
        paired.append(Deposit(b.purchase.portfolio, d.source_row_id, d.day, d.amount, CZK))
    return paired


def _cash_deposit(row: dict[str, str], where: str) -> _CashDeposit:
    if row[PAYMENT_CURRENCY] != CZK:
        msg = f"{where}: a Deposit in {row[PAYMENT_CURRENCY]!r}; converting a non-{CZK} Deposit isn't defined yet"
        raise NotImplementedError(msg)
    return _CashDeposit(
        where=where,
        jt_portfolio=row[PORTFOLIO],
        source_row_id=row[ROW_ID],
        day=_date(row, MOVED_DATE),
        amount=_decimal(row, PAYMENT),
    )


def _purchase(row: dict[str, str]) -> _PurchaseRow:
    """The Purchase in a row, its Fee unless that is zero, and the Conversion paying for it unless it is priced in
    CZK, with what the row paid.
    """
    movement_type = row[MOVEMENT_TYPE]
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
    fund = Fund(row[ISIN], row[FUND_NAME])
    # A Portfolio per Fund bought in each J&T portfolio.
    portfolio = Portfolio(Platform.JT, key=f"{row[PORTFOLIO]} {fund.isin}", name=fund.name)
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
        fund=fund,
        source_row_id=row[ROW_ID],
        day=day,
        units=_decimal(row, UNITS),
        unit_price=_decimal(row, UNIT_PRICE),
        currency=currency,
        amount=amount,
    )
    return _PurchaseRow(rows + Rows(purchases=[purchase]), purchase, row[PORTFOLIO], paid)


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
