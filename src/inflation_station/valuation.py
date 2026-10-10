"""Turns Purchases into a daily timeline of plain data. No I/O: everything it needs is passed in."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inflation_station.purchase import Purchase


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first Purchase's trade date to "today". Every series lines up with `dates`."""

    dates: tuple[date, ...]
    # The gross CZK of Purchases traded on or before each day; fees count as invested, so they count against the return.
    amount_invested: tuple[Decimal, ...]


def timeline(purchases: Sequence[Purchase], today: date) -> Timeline:
    """`purchases` must not be empty: with nothing bought there is no first day."""
    first = min(p.trade_date for p in purchases)
    dates = tuple(first + timedelta(days=n) for n in range((today - first).days + 1))

    invested_on: defaultdict[date, Decimal] = defaultdict(Decimal)
    for p in purchases:
        invested_on[p.trade_date] += p.gross_czk
    amount_invested = []
    total = Decimal(0)
    for d in dates:
        total += invested_on[d]
        amount_invested.append(total)

    return Timeline(dates=dates, amount_invested=tuple(amount_invested))
