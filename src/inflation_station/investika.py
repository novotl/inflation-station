"""Reads INVESTIKA's PDF statements, which come in pairs per Portfolio: a contract, numbered by its Číslo smlouvy.

The cash statement lists the money deposited and paid for investment; the holdings statement lists the units issued
for it. Their text, extracted with the layout kept, has one table row per line (two for a holdings row, whose fund name
wraps), its columns separated by runs of spaces.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, NamedTuple

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from inflation_station import czech
from inflation_station.currency import CZK
from inflation_station.domain import Deposit, Fee, Fund, Platform, Portfolio, Purchase, Rows
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal
    from pathlib import Path

CASH = "Pohyby na peněžním účtu"
HOLDINGS = "Transakce na majetkovém účtu"
KIND_NAMES = {CASH: "cash", HOLDINGS: "holdings"}
CONTRACT = "Číslo smlouvy"


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
_AMOUNT_AND_CURRENCY = re.compile(r"(?P<amount>.+) (?P<currency>[A-Z]{3})")
_CURRENCY = re.compile(r"[A-Z]{3}")
_TIME = re.compile(r"\d{2}:\d{2}:\d{2}")


@dataclass(frozen=True)
class Statement:
    """One statement's text lines; name is the file it came from, for messages."""

    name: str
    title: str
    portfolio: str
    lines: list[str]


class _Payment(NamedTuple):
    amount: Decimal
    as_written: str  # for messages


class RowError(Exception):
    """A problem with one row; the caller adds which statement and row."""


def read_pdf(path: Path) -> Statement:
    """The statement in an INVESTIKA PDF."""
    try:
        pages = PdfReader(path).pages
        lines = [line for page in pages for line in page.extract_text(extraction_mode="layout").splitlines()]
    except (OSError, PyPdfError) as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
    except KeyError as e:  # pypdf's layout mode, on a page without a content stream, such as a blank page
        msg = f"cannot read {path}: missing {e}"
        raise InflationStationError(msg) from e
    return statement(path.name, lines)


def statement(name: str, lines: list[str]) -> Statement:
    """Recognise a statement by its title, its first line of text."""
    title = next((line.strip() for line in lines if line.strip()), "")
    if title not in KIND_NAMES:
        msg = f"{name} is not an INVESTIKA statement: its title is neither {CASH!r} nor {HOLDINGS!r}"
        raise InflationStationError(msg)
    return Statement(name=name, title=title, portfolio=_portfolio(name, lines), lines=lines)


def _portfolio(name: str, lines: list[str]) -> str:
    """The Portfolio's contract number, on the line after its label."""
    stripped = [line.strip() for line in lines]
    for i, line in enumerate(stripped):
        if line == f"{CONTRACT}:":
            value = next((v for v in stripped[i + 1 :] if v), "")
            if value:
                return value
    msg = f"{name} has no {CONTRACT}"
    raise InflationStationError(msg)


def rows(statements: Iterable[Statement]) -> Rows:
    """Deposits, a Purchase per issue of units and the Fee charged on it, from statements that pair up by Portfolio.

    Raises on anything unknown.
    """
    deposits: list[Deposit] = []
    purchases: list[Purchase] = []
    fees: list[Fee] = []
    for cash, holdings in _pairs(statements):
        cash_rows = _Cash(cash, _contract(cash.portfolio))
        deposits += cash_rows.deposits
        row_ids: set[str] = set()
        for cells, next_cells in _holdings_rows(holdings):
            try:
                purchase, fee = _purchase(holdings.portfolio, cells, next_cells, cash_rows)
                purchases.append(_claim_row_id(purchase, row_ids))
            except RowError as e:
                msg = f"{holdings.name} row {cells[2]!r} ordered {cells[-1]}: {e}"
                raise InflationStationError(msg) from e
            if fee:
                # The Fee's identity is its Purchase's: one row of the holdings statement.
                fees.append(Fee(purchase.portfolio, purchase.source_row_id, purchase.day, fee, CZK))
    return Rows(deposits=deposits, purchases=purchases, fees=fees)


def _contract(number: str) -> Portfolio:
    """A Portfolio per contract, named by its number."""
    return Portfolio(Platform.INVESTIKA, key=number, name=number)


def _pairs(statements: Iterable[Statement]) -> list[tuple[Statement, Statement]]:
    """The (cash, holdings) statement of each Portfolio; raises unless every Portfolio has exactly one of each."""
    by_portfolio: dict[str, dict[str, list[Statement]]] = {}
    for s in statements:
        by_portfolio.setdefault(s.portfolio, {CASH: [], HOLDINGS: []})[s.title].append(s)
    problems = []
    for portfolio, kinds in by_portfolio.items():
        for title, other in ((CASH, HOLDINGS), (HOLDINGS, CASH)):
            found = kinds[title]
            names = ", ".join(s.name for s in found)
            if len(found) > 1:
                problems.append(f"Portfolio {portfolio} has {len(found)} {KIND_NAMES[title]} statements ({names})")
            elif found and not kinds[other]:
                problems.append(
                    f"Portfolio {portfolio} has a {KIND_NAMES[title]} statement ({names}) "
                    f"but no {KIND_NAMES[other]} statement"
                )
    if problems:
        msg = f"INVESTIKA statements come in pairs with the same {CONTRACT}: {'; '.join(problems)}"
        raise InflationStationError(msg)
    return [(kinds[CASH][0], kinds[HOLDINGS][0]) for kinds in by_portfolio.values()]


class _Cash:
    """The cash statement's Deposits, and its payments for investment, each claimed by the issue ordered on its day."""

    def __init__(self, cash: Statement, portfolio: Portfolio) -> None:
        """Read the Deposits and payments; raises on rows it doesn't know."""
        self._cash_name = cash.name
        self._portfolio = portfolio
        self.deposits: list[Deposit] = []
        self._deposit_counts: Counter[tuple[str, str]] = Counter()
        self._by_day: dict[date, list[_Payment]] = {}
        self._claimed: set[date] = set()
        for line in cash.lines:
            cells = _COLUMN_GAP.split(line.strip())
            match = _CASH_DATE.fullmatch(cells[0])
            if not match:
                continue
            if len(cells) not in {4, 5}:  # date, description, [symbol], type, amount
                msg = f"{cash.name} row on {cells[0]}: has {len(cells)} columns, expected 4 or 5"
                raise InflationStationError(msg)
            row = f"{cash.name} row {cells[1]!r} on {cells[0]}"
            try:
                self._read_row(match["date"], cells[1], cells[-2], cells[-1])
            except RowError as e:
                msg = f"{row}: {e}"
                raise InflationStationError(msg) from e
            except NotImplementedError as e:
                msg = f"{row}: {e}"
                raise NotImplementedError(msg) from e

    def _read_row(self, day: str, description: str, kind: str, amount_cell: str) -> None:
        if description == PAYMENT:
            if kind != "Debet":
                msg = f"Typ is {kind!r}, expected 'Debet'"
                raise RowError(msg)
            amount = _cash_amount(amount_cell)
            self._by_day.setdefault(_date(day, "Datum"), []).append(_Payment(_decimal(amount, "Částka"), amount))
        elif description == DEPOSIT:
            if kind != "Kredit":
                msg = f"Typ is {kind!r}, expected 'Kredit'"
                raise RowError(msg)
            self.deposits.append(self._deposit(_date(day, "Datum"), amount_cell))
        elif not _is_skipped(description):
            msg = "unknown transaction type"
            raise RowError(msg)

    def _deposit(self, day: date, amount_cell: str) -> Deposit:
        match = _AMOUNT_AND_CURRENCY.fullmatch(amount_cell)
        if not match:
            msg = f"Částka {amount_cell!r} is not an amount like '5 000,00 CZK'"
            raise RowError(msg)
        amount = _decimal(match["amount"], "Částka")
        if match["currency"] != CZK:
            msg = f"a Deposit in {match['currency']!r}; only {CZK} Deposits can be imported yet"
            raise NotImplementedError(msg)
        # The cash statement gives a Deposit no time or reference: identical ones on one day are told apart by count.
        key = (day.isoformat(), str(amount))
        self._deposit_counts[key] += 1
        source_row_id = ";".join((*key, str(self._deposit_counts[key])))
        return Deposit(self._portfolio, source_row_id, day, amount, CZK)

    def claim(self, order_day: date) -> _Payment:
        """The payment made on an issue's order day; raises unless there is exactly one."""
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
    """The fee, rounding and fund lines: the payment they're part of gives the Purchase and its Fee."""
    return description == ROUNDING or description.startswith(FEE_PREFIX) or description.endswith(FUND_LINE_SUFFIX)


def _holdings_rows(holdings: Statement) -> list[tuple[list[str], list[str]]]:
    """The cells of each transaction's two lines: those whose second column is an ISIN, and the next non-blank line."""
    cells = [_COLUMN_GAP.split(line.strip()) for line in holdings.lines if line.strip()]
    return [
        (row, cells[i + 1] if i + 1 < len(cells) else [])
        for i, row in enumerate(cells)
        if len(row) > 2 and _ISIN.fullmatch(row[1])  # noqa: PLR2004 - name, ISIN, type
    ]


def _purchase(portfolio: str, cells: list[str], next_cells: list[str], payments: _Cash) -> tuple[Purchase, Decimal]:
    """The Purchase in a holdings row and the CZK of its Fee, claiming the payment it was bought with."""
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
    if net_currency != CZK:
        msg = f"Částka is in {net_currency!r}, expected {CZK!r}"
        raise RowError(msg)
    if unit_price_currency != net_currency:
        # Units priced in another currency would be bought with a Conversion, which the statements don't show.
        msg = f"Cena / kus is in {unit_price_currency!r}, expected {CZK!r} like Částka"
        raise RowError(msg)

    paid, paid_as_written = payments.claim(_date(ordered, "Datum pokynu"))
    net_amount = _decimal(net, "Částka")
    if paid < net_amount:
        msg = f"payment {paid_as_written} is less than the issue's Částka {net}"
        raise RowError(msg)

    try:
        settled_at = datetime.strptime(f"{settled} {settled_time}", "%d.%m.%Y %H:%M:%S")  # noqa: DTZ007 - naive, like the dates
    except ValueError as e:
        msg = f"Datum vypořádání {settled!r} {settled_time!r} is not a date and time like '31.12.2026' '23:59:59'"
        raise RowError(msg) from e
    purchase = Purchase(
        portfolio=_contract(portfolio),
        fund=Fund(isin, " ".join([name_start, *name_end])),
        source_row_id=settled_at.isoformat(),
        # The month-end price the units were issued at; see docs/adr/0001-investika-trade-date-is-the-price-date.md.
        day=_date(price_date, "Datum ceny"),
        units=_decimal(units, "Počet kusů"),
        unit_price=_decimal(unit_price, "Cena / kus"),
        currency=unit_price_currency,
        amount=net_amount,
    )
    # The Fee is the payment less what bought units: the entry fee and the rounding.
    return purchase, paid - net_amount


def _claim_row_id(purchase: Purchase, row_ids: set[str]) -> Purchase:
    """The purchase, unless an earlier issue settled at the same time; the store would drop it as already present."""
    if purchase.source_row_id in row_ids:
        msg = (
            f"settled at {purchase.source_row_id}, like an earlier issue; "
            "the settlement time identifies an issue, so the import cannot tell them apart"
        )
        raise RowError(msg)
    row_ids.add(purchase.source_row_id)
    return purchase


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
