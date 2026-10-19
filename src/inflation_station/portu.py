"""Reads Portu transaction exports: semicolons, Czech headers, `1 501,01` numbers, `DD.MM.YYYY` dates, newest first.

Portu is a Managed Portfolio: it decides the Purchases, Sales, Conversions and Fees; you only make the Deposits.
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from inflation_station import czech
from inflation_station.currency import CZK
from inflation_station.currency import code as currency_code
from inflation_station.domain import Conversion, Deposit, Fee, Fund, Platform, Portfolio, Purchase, Rows, Sale
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path

# The type is what `Typ` says before its first spaced en dash, e.g. "Nákup" for a buy, whatever detail follows.
DEPOSIT = "Vklad z bankovního účtu"
PURCHASE = "Nákup"
SALE = "Prodej"
FOREX_BUY = "Forex nákup"
FOREX_SELL = "Forex prodej"
FEE = "Poplatek"
TYPES = (DEPOSIT, PURCHASE, SALE, FOREX_BUY, FOREX_SELL, FEE)
TYPE_SEPARATOR = " \u2013 "
# A currency pair in a forex leg's detail: the buy leg names its own currency first ("EUR/CZK"), the sell leg its own
# ("CZK/EUR").
_CURRENCY_PAIR = re.compile(r"(?P<first>[A-Z]{3})/(?P<second>[A-Z]{3})")

# The columns read from the export, each named once.
DATE = "Datum"
PORTFOLIO = "Název"
TYPE = "Typ"
SYMBOL = "Symbol"
ISIN = "ISIN"
UNITS = "Kusy / Pozice"
UNIT_PRICE = "Cena"
AMOUNT = "Hodnota"
CURRENCY = "Měna"
COLUMNS = (DATE, PORTFOLIO, TYPE, SYMBOL, ISIN, UNITS, UNIT_PRICE, AMOUNT, CURRENCY)
# What an export's header starts with; no other export we read starts this way.
SIGNATURE = (DATE, PORTFOLIO, TYPE)


class RowError(Exception):
    """A problem with one row; read_export adds which file and row."""


def is_export(path: Path) -> bool:
    """Whether the file's header is a Portu export's. Raises if the file can't be read."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f, delimiter=";"), [])
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    return tuple(header[: len(SIGNATURE)]) == SIGNATURE


@dataclass(frozen=True)
class _ForexLeg:
    """One side of a Conversion: a Forex nákup brings `amount` in, a Forex prodej takes it out."""

    line_num: int
    portfolio: Portfolio
    source_row_id: str
    day: date
    row_type: str
    detail: str
    amount: Decimal
    currency: str

    def pair_key(self) -> tuple[object, ...]:
        """What both legs of one Conversion share: Portfolio, day, and the detail, a currency pair in either order."""
        pair = _CURRENCY_PAIR.fullmatch(self.detail)
        detail = frozenset(pair.groups()) if pair else self.detail
        return (self.portfolio, self.day, detail)


def read_export(path: Path) -> Rows:
    """Return every row of a Portu export. Raises on anything it doesn't understand, so nothing is half-read."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a Portu export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            lines = [(reader.line_num, row) for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    # Exports are full-history, so a row has the same identity in every one of them. Exact repeats are told apart by
    # how many came before, counted oldest (last) first, so a repeat in a later export only adds to the count.
    occurrences: Counter[tuple[str, ...]] = Counter()
    rows = Rows()
    legs: list[_ForexLeg] = []
    for line_num, row in reversed(lines):
        try:
            read = _row(line_num, row, occurrences)
        except RowError as e:
            msg = f"{path.name} row {line_num}: {e}"
            raise InflationStationError(msg) from e
        if isinstance(read, _ForexLeg):
            legs.append(read)
        else:
            rows += read
    try:
        conversions = _conversions(legs)
    except RowError as e:
        msg = f"{path.name} {e}"
        raise InflationStationError(msg) from e
    return rows + Rows(conversions=conversions)


def _row(line_num: int, row: dict[str, str], occurrences: Counter[tuple[str, ...]]) -> Rows | _ForexLeg:
    row_type, _, detail = row[TYPE].partition(TYPE_SEPARATOR)
    if row_type not in TYPES:
        msg = f"unknown type {row_type!r}"
        raise RowError(msg)
    day = _date(row)
    amount = _decimal(row, AMOUNT)
    try:
        currency = currency_code(row[CURRENCY])
    except ValueError as e:
        msg = f"{CURRENCY} {e}"
        raise RowError(msg) from e
    if row_type == DEPOSIT and currency != CZK:
        msg = f"a {row_type} row is in {currency!r}, expected {CZK!r}"
        raise RowError(msg)
    key = (day.isoformat(), row_type, row[SYMBOL], str(amount), currency)
    # Counted per Portfolio, so one Portfolio's rows never shift another's count.
    occurrences[row[PORTFOLIO], *key] += 1
    source_row_id = ";".join((*key, str(occurrences[row[PORTFOLIO], *key])))
    # The Portfolio is identified by its name: a renamed one is a new Portfolio.
    portfolio = Portfolio(Platform.PORTU, key=row[PORTFOLIO], name=row[PORTFOLIO])
    # Money in is positive, money out negative; every row type moves it one way only.
    outgoing = row_type in {PURCHASE, FOREX_SELL, FEE}
    if (amount < 0) != outgoing:
        msg = f"a {row_type} row's {AMOUNT} {row[AMOUNT]!r} is {'positive' if outgoing else 'negative'}"
        raise RowError(msg)
    amount = abs(amount)
    if row_type in {FOREX_BUY, FOREX_SELL}:
        return _ForexLeg(line_num, portfolio, source_row_id, day, row_type, detail, amount, currency)
    if row_type == DEPOSIT:
        return Rows(deposits=[Deposit(portfolio, source_row_id, day, amount, currency)])
    if row_type == FEE:
        return Rows(fees=[Fee(portfolio, source_row_id, day, amount, currency)])
    if not row[ISIN]:
        msg = f"a {row_type} row has no ISIN"
        raise RowError(msg)
    trade = (Purchase if row_type == PURCHASE else Sale)(
        portfolio=portfolio,
        # Portu names a fund only by its ticker.
        fund=Fund(row[ISIN], row[SYMBOL]),
        source_row_id=source_row_id,
        day=day,
        # Units are exported unsigned.
        units=_decimal(row, UNITS),
        unit_price=_decimal(row, UNIT_PRICE),
        currency=currency,
        amount=amount,
    )
    return Rows(purchases=[trade]) if isinstance(trade, Purchase) else Rows(sales=[trade])


def _conversions(legs: list[_ForexLeg]) -> list[Conversion]:
    """Each Forex prodej with its Forex nákup: on the same day, in the same Portfolio, with the same detail (a currency
    pair, in either order). Raises naming a leg with no other leg, or more than one.
    """
    by_key: dict[tuple[object, ...], list[_ForexLeg]] = {}
    for leg in legs:
        by_key.setdefault(leg.pair_key(), []).append(leg)
    conversions = []
    for pair in by_key.values():
        sells = [leg for leg in pair if leg.row_type == FOREX_SELL]
        buys = [leg for leg in pair if leg.row_type == FOREX_BUY]
        first = min(pair, key=lambda leg: leg.line_num)
        if len(sells) != 1 or len(buys) != 1:
            msg = (
                f"row {first.line_num}: cannot pair the {first.row_type} {first.detail!r} into a Conversion: that day "
                f"the Portfolio has {len(sells)} {FOREX_SELL} and {len(buys)} {FOREX_BUY} rows with this detail, "
                "expected one of each"
            )
            raise RowError(msg)
        if sells[0].currency == buys[0].currency:
            msg = f"row {first.line_num}: both legs of the {first.detail!r} Conversion are in {first.currency}"
            raise RowError(msg)
        sell, buy = sells[0], buys[0]
        conversions.append(
            Conversion(
                portfolio=sell.portfolio,
                # The sell leg's: unlike which leg the export lists first, it is the same in every export.
                source_row_id=sell.source_row_id,
                day=sell.day,
                from_amount=sell.amount,
                from_currency=sell.currency,
                to_amount=buy.amount,
                to_currency=buy.currency,
            )
        )
    return conversions


def _date(row: dict[str, str]) -> date:
    try:
        return datetime.strptime(row[DATE], "%d.%m.%Y").date()  # noqa: DTZ007 - the export's dates are naive
    except ValueError as e:
        msg = f"{DATE} {row[DATE]!r} is not a date like '31.12.2021'"
        raise RowError(msg) from e


def _decimal(row: dict[str, str], column: str) -> Decimal:
    number = czech.decimal(row[column])
    if number is None:
        msg = f"{column} {row[column]!r} is not a number like '1 501,01'"
        raise RowError(msg)
    return number
