from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True)
class Purchase:
    """A buy of fund units, independent of the platform it was imported from.

    (platform, account_id, source_row_id) identifies the source row, so re-imports never duplicate it.
    """

    platform: str
    account_id: str
    source_row_id: str
    isin: str
    fund_name: str
    trade_date: date
    units: Decimal
    unit_price: Decimal
    unit_price_currency: str
    gross_czk: Decimal
    fee: Decimal
    fee_currency: str


def fund_names(purchases: Iterable[Purchase]) -> dict[str, str]:
    """The name each purchased fund had in its latest Purchase, by ISIN, sorted by ISIN."""
    latest = {p.isin: p.fund_name for p in sorted(purchases, key=lambda p: p.trade_date)}
    return dict(sorted(latest.items()))


def first_trade_dates(purchases: Iterable[Purchase]) -> dict[str, date]:
    """The first trade date of the Purchases priced in each currency, by currency, sorted by currency."""
    first: dict[str, date] = {}
    for p in sorted(purchases, key=lambda p: p.trade_date):
        first.setdefault(p.unit_price_currency, p.trade_date)
    return dict(sorted(first.items()))
