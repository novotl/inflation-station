"""A Managed Portfolio's ledger: every row of its export, each moving its Cash and, for buys and sells, its units."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date
    from decimal import Decimal

# What a row is. Only Deposits are money invested (ADR-0002); buys and sells are not Purchases.
DEPOSIT, BUY, SELL, FOREX_BUY, FOREX_SELL, FEE = "deposit", "buy", "sell", "forex_buy", "forex_sell", "fee"


@dataclass(frozen=True)
class LedgerEntry:
    """One row of a Managed Portfolio's export, independent of the platform it was imported from.

    (platform, portfolio_id, source_row_id) identifies the source row, so re-imports never duplicate it.
    """

    platform: str
    portfolio_id: str
    source_row_id: str
    day: date
    kind: str
    # The fund bought or sold, and the change in the units held of it: up on buys, down on sells. "" and 0 otherwise.
    isin: str
    fund_name: str
    units: Decimal
    # The price of a unit in `currency` on buys and sells; None otherwise.
    unit_price: Decimal | None
    # The change in Cash in `currency`: in (+) or out (-).
    amount: Decimal
    currency: str


def fund_names(entries: Iterable[LedgerEntry]) -> dict[str, str]:
    """The name each fund had in its latest buy or sell, by ISIN, sorted by ISIN."""
    latest = {e.isin: e.fund_name for e in sorted(entries, key=lambda e: e.day) if e.isin}
    return dict(sorted(latest.items()))


def first_cash_days(entries: Iterable[LedgerEntry]) -> dict[str, date]:
    """The day of the first entry moving Cash in each currency, by currency, sorted by currency."""
    first: dict[str, date] = {}
    for e in sorted(entries, key=lambda e: e.day):
        first.setdefault(e.currency, e.day)
    return dict(sorted(first.items()))
