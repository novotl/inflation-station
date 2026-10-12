"""Reads Portu transaction exports: semicolons, Czech headers, `1 501,01` numbers, `DD.MM.YYYY` dates, newest first.

Portu is a Managed Account (ADR-0002): every row is a LedgerEntry, and only its Deposits are money invested.
"""

import csv
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station import czech
from inflation_station.errors import InflationStationError
from inflation_station.ledger import BUY, DEPOSIT, FEE, FOREX_BUY, FOREX_SELL, SELL, LedgerEntry

if TYPE_CHECKING:
    from pathlib import Path

# The type is what `Typ` says before its first spaced en dash, e.g. "Nákup" for a buy, whatever detail follows.
KINDS = {
    "Vklad z bankovního účtu": DEPOSIT,
    "Nákup": BUY,
    "Prodej": SELL,
    "Forex nákup": FOREX_BUY,
    "Forex prodej": FOREX_SELL,
    "Poplatek": FEE,
}
TYPE_SEPARATOR = " \u2013 "

# The columns read from the export, each named once.
DATE = "Datum"
ACCOUNT_ID = "Název"
TYPE = "Typ"
SYMBOL = "Symbol"
ISIN = "ISIN"
UNITS = "Kusy / Pozice"
UNIT_PRICE = "Cena"
AMOUNT = "Hodnota"
CURRENCY = "Měna"
COLUMNS = (DATE, ACCOUNT_ID, TYPE, SYMBOL, ISIN, UNITS, UNIT_PRICE, AMOUNT, CURRENCY)
# What an export's header starts with; no other export we read starts this way.
SIGNATURE = (DATE, ACCOUNT_ID, TYPE)


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


def read_export(path: Path) -> list[LedgerEntry]:
    """Return every row of a Portu export. Raises on anything it doesn't understand, so nothing is half-read."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                msg = f"{path.name} is not a Portu export: missing columns {', '.join(missing)}"
                raise InflationStationError(msg)
            rows = [(reader.line_num, row) for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    # Exports are full-history, so a row has the same identity in every one of them. Exact repeats are told apart by
    # how many came before, counted oldest (last) first, so a repeat in a later export only adds to the count.
    occurrences: Counter[tuple[str, ...]] = Counter()
    entries = []
    for line_num, row in reversed(rows):
        try:
            entry = _entry(row, occurrences)
        except RowError as e:
            msg = f"{path.name} row {line_num}: {e}"
            raise InflationStationError(msg) from e
        entries.append(entry)
    return entries[::-1]


def _entry(row: dict[str, str], occurrences: Counter[tuple[str, ...]]) -> LedgerEntry:
    row_type = row[TYPE].split(TYPE_SEPARATOR, 1)[0]
    kind = KINDS.get(row_type)
    if kind is None:
        msg = f"unknown type {row_type!r}"
        raise RowError(msg)
    day = _date(row)
    amount = _decimal(row, AMOUNT)
    if kind == DEPOSIT and row[CURRENCY] != "CZK":
        msg = f"a {row_type} row is in {row[CURRENCY]!r}, expected 'CZK'"
        raise RowError(msg)
    isin, units, unit_price = "", Decimal(0), None
    if kind in {BUY, SELL}:
        if not row[ISIN]:
            msg = f"a {row_type} row has no ISIN"
            raise RowError(msg)
        isin, units, unit_price = row[ISIN], _decimal(row, UNITS), _decimal(row, UNIT_PRICE)
        # Units are exported unsigned.
        units = -units if kind == SELL else units
    key = (day.isoformat(), row_type, row[SYMBOL], str(amount), row[CURRENCY])
    # Counted per Account, so one portfolio's rows never shift another's count.
    occurrences[row[ACCOUNT_ID], *key] += 1
    return LedgerEntry(
        platform="portu",
        account_id=row[ACCOUNT_ID],
        source_row_id=";".join((*key, str(occurrences[row[ACCOUNT_ID], *key]))),
        day=day,
        kind=kind,
        isin=isin,
        # Portu names a fund only by its ticker.
        fund_name=row[SYMBOL] if isin else "",
        units=units,
        unit_price=unit_price,
        amount=amount,
        currency=row[CURRENCY],
    )


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
