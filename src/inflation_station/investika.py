"""Reads INVESTIKA's PDF statements, which come in pairs per contract (Číslo smlouvy).

The cash statement lists the money paid in; the holdings statement lists the units issued for it. Their text, extracted
with the layout kept, has one table row per line (two for a holdings row, whose fund name wraps), its columns separated
by runs of spaces.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from inflation_station import czech
from inflation_station.errors import InflationStationError
from inflation_station.purchase import Purchase

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal
    from pathlib import Path

CASH = "Pohyby na peněžním účtu"
HOLDINGS = "Transakce na majetkovém účtu"
KIND_NAMES = {CASH: "cash", HOLDINGS: "holdings"}
CONTRACT = "Číslo smlouvy:"

# Cash statement rows.
PAYMENT = "Odchozí platba z VÚ na investici"
DEPOSIT = "Investice klienta - vklad na VÚ"
ROUNDING = "Zaokrouhlení"
FEE_PREFIX = "Vstupní poplatek"
FUND_LINE_SUFFIX = ", Pravidelná investice"

# Holdings statement rows.
ISSUE = "Vydání CP"

_COLUMN_GAP = re.compile(r"\s{2,}")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}\d")
_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_CASH_DATE = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})( \d{2}:\d{2}:\d{2})?")
_CASH_AMOUNT = re.compile(r"(?P<amount>.+) CZK")
_CURRENCY = re.compile(r"[A-Z]{3}")
_TIME = re.compile(r"\d{2}:\d{2}:\d{2}")


@dataclass(frozen=True)
class Statement:
    """One statement's text lines; name is the file it came from, for messages."""

    name: str
    title: str
    contract: str
    lines: list[str]


class RowError(Exception):
    """A problem with one row; the caller adds which statement and row."""


def read_pdf(path: Path) -> Statement:
    """The statement in an Investika PDF."""
    try:
        pages = PdfReader(path).pages
        lines = [line for page in pages for line in page.extract_text(extraction_mode="layout").splitlines()]
    except (OSError, PyPdfError) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    return statement(path.name, lines)


def statement(name: str, lines: list[str]) -> Statement:
    """Recognise a statement by its title, its first line of text."""
    title = next((line.strip() for line in lines if line.strip()), "")
    if title not in KIND_NAMES:
        msg = f"{name} is not an Investika statement: its title is neither {CASH!r} nor {HOLDINGS!r}"
        raise InflationStationError(msg)
    return Statement(name=name, title=title, contract=_contract(name, lines), lines=lines)


def _contract(name: str, lines: list[str]) -> str:
    """The contract number, on the line after its label."""
    stripped = [line.strip() for line in lines]
    for i, line in enumerate(stripped):
        if line == CONTRACT:
            value = next((v for v in stripped[i + 1 :] if v), "")
            if value:
                return value
    msg = f"{name} has no {CONTRACT.removesuffix(':')}"
    raise InflationStationError(msg)


def purchases(statements: Iterable[Statement]) -> list[Purchase]:
    """One Purchase per issue of units, from statements that pair up by contract. Raises on anything unknown."""
    result = []
    for cash, holdings in _pairs(statements):
        payments = _Payments(cash)
        for cells, next_cells in _holdings_rows(holdings):
            try:
                result.append(_issue(holdings.contract, cells, next_cells, payments))
            except RowError as e:
                msg = f"{holdings.name} row {cells[2]!r} ordered {cells[-1]}: {e}"
                raise InflationStationError(msg) from e
    return result


def _pairs(statements: Iterable[Statement]) -> list[tuple[Statement, Statement]]:
    """The (cash, holdings) statement of each contract; raises unless every contract has exactly one of each."""
    by_contract: dict[str, dict[str, list[Statement]]] = {}
    for s in statements:
        by_contract.setdefault(s.contract, {CASH: [], HOLDINGS: []})[s.title].append(s)
    problems = []
    for contract, kinds in by_contract.items():
        for title, other in ((CASH, HOLDINGS), (HOLDINGS, CASH)):
            found = kinds[title]
            names = ", ".join(s.name for s in found)
            if len(found) > 1:
                problems.append(f"contract {contract} has {len(found)} {KIND_NAMES[title]} statements ({names})")
            elif found and not kinds[other]:
                problems.append(
                    f"contract {contract} has a {KIND_NAMES[title]} statement ({names}) "
                    f"but no {KIND_NAMES[other]} statement"
                )
    if problems:
        msg = f"Investika statements come in pairs with the same {CONTRACT.removesuffix(':')}: {'; '.join(problems)}"
        raise InflationStationError(msg)
    return [(kinds[CASH][0], kinds[HOLDINGS][0]) for kinds in by_contract.values()]


class _Payments:
    """The cash statement's payments for investment, each claimed by the one issue ordered on its day."""

    def __init__(self, cash: Statement) -> None:
        """Read the payments; raises on rows it doesn't know."""
        self._cash_name = cash.name
        self._by_day: dict[date, list[tuple[Decimal, str]]] = {}
        self._claimed: set[date] = set()
        for line in cash.lines:
            cells = _COLUMN_GAP.split(line.strip())
            match = _CASH_DATE.fullmatch(cells[0])
            if match and len(cells) >= 4:  # noqa: PLR2004 - date, description, [symbol], type, amount
                try:
                    self._read_row(match["date"], cells[1], cells[-1])
                except RowError as e:
                    msg = f"{cash.name} row {cells[1]!r} on {cells[0]}: {e}"
                    raise InflationStationError(msg) from e

    def _read_row(self, day: str, description: str, amount: str) -> None:
        if description == PAYMENT:
            amount = _cash_amount(amount)
            self._by_day.setdefault(_date(day, "Datum"), []).append((_decimal(amount, "Částka"), amount))
        elif not _is_skipped(description):
            msg = "unknown transaction type"
            raise RowError(msg)

    def claim(self, order_day: date) -> tuple[Decimal, str]:
        """The payment made on an issue's order day, as a number and as written; raises unless there is exactly one."""
        matches = self._by_day.get(order_day, [])
        if not matches:
            msg = f"no {PAYMENT!r} on its order date in {self._cash_name}"
            raise RowError(msg)
        if len(matches) > 1:
            msg = f"{len(matches)} {PAYMENT!r} on its order date in {self._cash_name}; cannot tell which paid"
            raise RowError(msg)
        if order_day in self._claimed:
            msg = f"another issue was ordered on the same day; cannot tell which {PAYMENT!r} paid for which"
            raise RowError(msg)
        self._claimed.add(order_day)
        return matches[0]


def _is_skipped(description: str) -> bool:
    """Deposits, and the fee, rounding and fund lines: gross and fee come from the payment, which they're part of."""
    return (
        description in {DEPOSIT, ROUNDING}
        or description.startswith(FEE_PREFIX)
        or description.endswith(FUND_LINE_SUFFIX)
    )


def _holdings_rows(holdings: Statement) -> list[tuple[list[str], list[str]]]:
    """The cells of each transaction's two lines: those whose second column is an ISIN, and the next non-blank line."""
    cells = [_COLUMN_GAP.split(line.strip()) for line in holdings.lines if line.strip()]
    return [
        (row, cells[i + 1] if i + 1 < len(cells) else [])
        for i, row in enumerate(cells)
        if len(row) > 2 and _ISIN.fullmatch(row[1])  # noqa: PLR2004 - name, ISIN, type
    ]


def _issue(contract: str, cells: list[str], next_cells: list[str], payments: _Payments) -> Purchase:
    """The Purchase in a holdings row, claiming the payment it was bought with."""
    if cells[2] != ISSUE:
        msg = "unknown transaction type"
        raise RowError(msg)
    if len(cells) != 9:  # noqa: PLR2004 - the holdings table's columns
        msg = f"has {len(cells)} columns, expected 9"
        raise RowError(msg)
    name_start, isin, _, units, unit_price, net, price_date, settled, ordered = cells
    # The second line holds the end of the fund name, the currencies of Cena / kus and Částka, and the settlement time.
    if len(next_cells) < 3 or not (  # noqa: PLR2004 - currency, currency, time
        _CURRENCY.fullmatch(next_cells[-3]) and _CURRENCY.fullmatch(next_cells[-2]) and _TIME.fullmatch(next_cells[-1])
    ):
        msg = "its second line does not end with the currencies and the settlement time"
        raise RowError(msg)
    name_end = next_cells[:-3]
    unit_price_currency, net_currency, settled_time = next_cells[-3:]
    if net_currency != "CZK":
        msg = f"Částka is in {net_currency!r}, expected 'CZK'"
        raise RowError(msg)

    gross, gross_text = payments.claim(_date(ordered, "Datum pokynu"))
    net_amount = _decimal(net, "Částka")
    if gross < net_amount:
        msg = f"payment {gross_text} is less than the issue's Částka {net}"
        raise RowError(msg)

    try:
        settled_at = datetime.strptime(f"{settled} {settled_time}", "%d.%m.%Y %H:%M:%S")  # noqa: DTZ007 - naive, like the dates
    except ValueError as e:
        msg = f"Datum vypořádání {settled!r} {settled_time!r} is not a date and time like '31.12.2026' '23:59:59'"
        raise RowError(msg) from e
    return Purchase(
        platform="investika",
        account_id=contract,
        source_row_id=settled_at.isoformat(),
        isin=isin,
        fund_name=" ".join([name_start, *name_end]),
        # The month-end price the units were issued at; see docs/adr/0001-investika-trade-date-is-the-price-date.md.
        trade_date=_date(price_date, "Datum ceny"),
        units=_decimal(units, "Počet kusů"),
        unit_price=_decimal(unit_price, "Cena / kus"),
        unit_price_currency=unit_price_currency,
        gross_czk=gross,
        # The payment less what bought units: the entry fee and the rounding.
        fee=gross - net_amount,
        fee_currency="CZK",
    )


def _cash_amount(text: str) -> str:
    match = _CASH_AMOUNT.fullmatch(text)
    if not match:
        msg = f"Částka {text!r} is not an amount like '5 000,00 CZK'"
        raise RowError(msg)
    return match["amount"]


def _date(text: str, column: str) -> date:
    try:
        if _DATE.fullmatch(text):
            return datetime.strptime(text, "%d.%m.%Y").date()  # noqa: DTZ007 - the statements' dates are naive
    except ValueError:
        pass
    msg = f"{column} {text!r} is not a date like '31.12.2026'"
    raise RowError(msg)


def _decimal(text: str, column: str) -> Decimal:
    number = czech.decimal(text)
    if number is None:
        msg = f"{column} {text!r} is not a number like '1 501,01'"
        raise RowError(msg)
    return number
