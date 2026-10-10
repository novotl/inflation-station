"""Turns Purchases and prices into a daily timeline of plain data. No I/O: everything it needs is passed in."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station.purchase import fund_names

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from inflation_station.fund_price import FundPrice
    from inflation_station.purchase import Purchase

# Until FX conversion exists, only funds priced in CZK can be valued in CZK.
VALUED_CURRENCY = "CZK"
NO_PRICES = "no prices stored"


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first Purchase's trade date to "today". Every series lines up with `dates`.

    A value is None on a day it can't be known: units are held, but no price is known yet.
    """

    dates: tuple[date, ...]
    # The gross CZK of Purchases traded on or before each day; fees count as invested, so they count against the return.
    amount_invested: tuple[Decimal, ...]
    # The latest fund name by ISIN, for every fund purchased.
    fund_names: Mapping[str, str]
    # CZK value by ISIN, for the funds that can be valued: units held x the last known price on or before the day.
    fund_values: Mapping[str, tuple[Decimal | None, ...]]
    # The sum of `fund_values`; None when no fund can be valued.
    portfolio_value: tuple[Decimal | None, ...] | None
    # Why each fund left out of `fund_values` couldn't be valued, by ISIN.
    not_valued: Mapping[str, str]


def timeline(purchases: Sequence[Purchase], *, prices: Sequence[FundPrice] = (), today: date) -> Timeline:
    """`purchases` must not be empty: with nothing bought there is no first day."""
    first = min(p.trade_date for p in purchases)
    dates = tuple(first + timedelta(days=n) for n in range((today - first).days + 1))

    fund_values: dict[str, tuple[Decimal | None, ...]] = {}
    not_valued: dict[str, str] = {}
    for isin in sorted({p.isin for p in purchases}):
        fund_prices = [p for p in prices if p.isin == isin]
        currencies = sorted({p.currency for p in fund_prices})
        if not fund_prices:
            not_valued[isin] = NO_PRICES
        elif currencies != [VALUED_CURRENCY]:
            not_valued[isin] = f"priced in {', '.join(currencies)}"
        else:
            fund_values[isin] = _fund_value(dates, [p for p in purchases if p.isin == isin], fund_prices)

    return Timeline(
        dates=dates,
        amount_invested=_running_total(dates, [(p.trade_date, p.gross_czk) for p in purchases]),
        fund_names=fund_names(purchases),
        fund_values=fund_values,
        portfolio_value=_sum(fund_values.values()) if fund_values else None,
        not_valued=not_valued,
    )


def _fund_value(
    dates: Sequence[date], purchases: Sequence[Purchase], prices: Sequence[FundPrice]
) -> tuple[Decimal | None, ...]:
    units_held = _running_total(dates, [(p.trade_date, p.units) for p in purchases])
    price_on = {p.day: p.price for p in prices}
    # The last price on or before the first day, so a holding is valued from day one when a price exists.
    last_price = max((p for p in prices if p.day <= dates[0]), key=lambda p: p.day, default=None)
    price = last_price.price if last_price else None
    values: list[Decimal | None] = []
    for d, units in zip(dates, units_held, strict=True):
        price = price_on.get(d, price)
        if not units:
            values.append(Decimal(0))
        else:
            values.append(None if price is None else units * price)
    return tuple(values)


def _running_total(dates: Sequence[date], amounts: Iterable[tuple[date, Decimal]]) -> tuple[Decimal, ...]:
    """The sum of the amounts dated on or before each day."""
    on: defaultdict[date, Decimal] = defaultdict(Decimal)
    for d, amount in amounts:
        on[d] += amount
    totals = []
    total = Decimal(0)
    for d in dates:
        total += on[d]
        totals.append(total)
    return tuple(totals)


def _sum(series: Iterable[tuple[Decimal | None, ...]]) -> tuple[Decimal | None, ...]:
    """Day-by-day sum of the series; None on a day any of them is None."""
    return tuple(None if None in day else sum(day, Decimal(0)) for day in zip(*series, strict=True))
