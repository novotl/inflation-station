"""Turns Purchases, Managed Accounts' ledgers, prices and price indices into a daily timeline of plain data.

No I/O: all of it is passed in.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station.ledger import DEPOSIT
from inflation_station.ledger import fund_names as held_fund_names
from inflation_station.purchase import fund_names

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from inflation_station.fund_price import FundPrice
    from inflation_station.fx_rate import FxRate
    from inflation_station.ledger import LedgerEntry
    from inflation_station.price_index import IndexLevel
    from inflation_station.purchase import Purchase

CZK = "CZK"
NO_PRICES = "no prices stored"


def no_rates(currency: str) -> str:
    """Why a fund priced in, or Cash held in, `currency` can't be valued when no rates of it are stored."""
    return f"no {currency} rates stored"


@dataclass(frozen=True)
class Hurdle:
    """What the money invested would need to be worth on each day to keep its purchasing power, by one price index.

    A value is None on a day the index is unknown for a Purchase or Deposit counted that day.
    """

    # Σ CZK x I(day) / I(date), over the gross CZK of Purchases and the Deposits dated on or before the day.
    values: tuple[Decimal | None, ...]
    # The first day whose index leans on an estimated month: the day after the last published month starts.
    estimated_from: date


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first Purchase or ledger entry to "today". Every series lines up with `dates`.

    A value is None on a day it can't be known: units are held, but no price is known yet.
    """

    dates: tuple[date, ...]
    # The gross CZK of Purchases plus the Deposits dated on or before each day; fees count as invested, so they count
    # against the return.
    amount_invested: tuple[Decimal, ...]
    # `amount_invested` by ISIN, for every fund purchased or held, counting only that fund's Purchases: a fund held in a
    # Managed Account has nothing invested in it (ADR-0002).
    fund_amount_invested: Mapping[str, tuple[Decimal, ...]]
    # The latest fund name by ISIN, for every fund purchased or held.
    fund_names: Mapping[str, str]
    # Units held by ISIN, for every fund purchased or held: the units of its Purchases traded, and of its buys less its
    # sells in Managed Accounts, on or before each day.
    units_held: Mapping[str, tuple[Decimal, ...]]
    # CZK value by ISIN, for the funds that can be valued: units held x the last known price on or before the day,
    # x the last known CZK rate on or before the day for funds not priced in CZK.
    fund_values: Mapping[str, tuple[Decimal | None, ...]]
    # Value in the fund's own currency by ISIN, for the same funds as `fund_values`: units held x the last known price
    # on or before the day.
    fund_currency_values: Mapping[str, tuple[Decimal | None, ...]]
    # The currency each fund in `fund_values` is priced in, by ISIN.
    fund_currencies: Mapping[str, str]
    # What each fund is priced in, by ISIN, for every fund purchased or held: the currencies of its prices, or the
    # currency of its latest Purchase (else of its latest buy or sell) when it has none.
    priced_in: Mapping[str, str]
    # The sum of `fund_values` and `cash_values`; None when no fund or Cash can be valued.
    portfolio_value: tuple[Decimal | None, ...] | None
    # Why each fund left out of `fund_values` couldn't be valued, by ISIN.
    not_valued: Mapping[str, str]
    # The inflation hurdle by price index series, for every series with index levels.
    hurdles: Mapping[str, Hurdle]
    # `hurdles` by ISIN, for every fund purchased or held, counting only that fund's Purchases.
    fund_hurdles: Mapping[str, Mapping[str, Hurdle]]
    # Cash in Managed Accounts by currency, for every currency in their ledgers: the sum of the entries dated on or
    # before each day. Negative when a hedging leg goes out a day before the other comes in.
    cash: Mapping[str, tuple[Decimal, ...]]
    # CZK value of `cash` by currency, for the currencies that can be valued: the balance x the last known CZK rate on
    # or before the day, for currencies other than CZK.
    cash_values: Mapping[str, tuple[Decimal | None, ...]]
    # The sum of `cash_values`; None when no Cash can be valued.
    cash_value: tuple[Decimal | None, ...] | None
    # Why the Cash in each currency left out of `cash_values` couldn't be valued, by currency.
    cash_not_valued: Mapping[str, str]


def timeline(  # noqa: PLR0913 - every input but the Purchases is keyword-only
    purchases: Sequence[Purchase],
    *,
    ledger: Sequence[LedgerEntry] = (),
    prices: Sequence[FundPrice] = (),
    rates: Sequence[FxRate] = (),
    index_levels: Sequence[IndexLevel] = (),
    today: date,
) -> Timeline:
    """`purchases` and `ledger` must not both be empty: with nothing bought or deposited there is no first day."""
    first = min([p.trade_date for p in purchases] + [e.day for e in ledger])
    dates = tuple(first + timedelta(days=n) for n in range((today - first).days + 1))

    isins = sorted({p.isin for p in purchases} | {e.isin for e in ledger if e.isin})
    purchased = {isin: [p for p in purchases if p.isin == isin] for isin in isins}
    traded = {isin: [e for e in ledger if e.isin == isin] for isin in isins}
    units_held = {
        isin: _running_total(
            dates, [(p.trade_date, p.units) for p in purchased[isin]] + [(e.day, e.units) for e in traded[isin]]
        )
        for isin in isins
    }
    invested = [(p.trade_date, p.gross_czk) for p in purchases] + [
        (e.day, e.amount) for e in ledger if e.kind == DEPOSIT
    ]
    fund_values: dict[str, tuple[Decimal | None, ...]] = {}
    fund_currency_values: dict[str, tuple[Decimal | None, ...]] = {}
    fund_currencies: dict[str, str] = {}
    not_valued: dict[str, str] = {}
    priced_in: dict[str, str] = {}
    for isin, units in units_held.items():
        fund_prices = [p for p in prices if p.isin == isin]
        currencies = sorted({p.currency for p in fund_prices})
        if currencies:
            priced_in[isin] = ", ".join(currencies)
        elif purchased[isin]:
            priced_in[isin] = max(purchased[isin], key=lambda p: p.trade_date).unit_price_currency
        else:
            priced_in[isin] = max(traded[isin], key=lambda e: e.day).currency
        if not fund_prices:
            not_valued[isin] = NO_PRICES
        elif len(currencies) > 1:
            not_valued[isin] = f"priced in {priced_in[isin]}"
        elif currencies != [CZK] and not any(r.currency == currencies[0] for r in rates):
            not_valued[isin] = no_rates(currencies[0])
        else:
            fund_currencies[isin] = currencies[0]
            unit_prices = _last_known(dates, [(p.day, p.price) for p in fund_prices])
            fund_currency_values[isin] = _zero_when_not_held(units, _times(units, unit_prices))
            fund_values[isin] = _zero_when_not_held(
                units, _times(fund_currency_values[isin], _czk_per_unit(dates, currencies[0], rates))
            )

    cash = {
        currency: _running_total(dates, [(e.day, e.amount) for e in ledger if e.currency == currency])
        for currency in sorted({e.currency for e in ledger})
    }
    cash_values: dict[str, tuple[Decimal | None, ...]] = {}
    cash_not_valued: dict[str, str] = {}
    for currency, balances in cash.items():
        if currency != CZK and not any(r.currency == currency for r in rates):
            cash_not_valued[currency] = no_rates(currency)
        else:
            # Taken as it is, so a negative balance counts against the value.
            cash_values[currency] = _zero_when_not_held(
                balances, _times(balances, _czk_per_unit(dates, currency, rates))
            )
    values = [*fund_values.values(), *cash_values.values()]

    levels_by_series = {
        series: [i for i in index_levels if i.series == series] for series in sorted({i.series for i in index_levels})
    }
    return Timeline(
        dates=dates,
        amount_invested=_running_total(dates, invested),
        fund_amount_invested={isin: _amount_invested(dates, bought) for isin, bought in purchased.items()},
        # A fund's name on a Platform where you pick the funds wins over its ticker in a Managed Account.
        fund_names=dict(sorted((held_fund_names(ledger) | fund_names(purchases)).items())),
        units_held=units_held,
        fund_values=fund_values,
        fund_currency_values=fund_currency_values,
        fund_currencies=fund_currencies,
        priced_in=priced_in,
        portfolio_value=_sum(values) if values else None,
        not_valued=not_valued,
        hurdles={series: _hurdle(dates, invested, levels) for series, levels in levels_by_series.items()},
        fund_hurdles={
            isin: {
                series: _hurdle(dates, [(p.trade_date, p.gross_czk) for p in bought], levels)
                for series, levels in levels_by_series.items()
            }
            for isin, bought in purchased.items()
        },
        cash=cash,
        cash_values=cash_values,
        cash_value=_sum(cash_values.values()) if cash_values else None,
        cash_not_valued=cash_not_valued,
    )


def _amount_invested(dates: Sequence[date], purchases: Iterable[Purchase]) -> tuple[Decimal, ...]:
    """The gross CZK of `purchases` traded on or before each day."""
    return _running_total(dates, [(p.trade_date, p.gross_czk) for p in purchases])


def _hurdle(dates: Sequence[date], invested: Sequence[tuple[date, Decimal]], levels: Sequence[IndexLevel]) -> Hurdle:
    """`invested` is each Purchase's or Deposit's (date, CZK). `levels` must not be empty, and must be one series'
    levels for consecutive months.
    """
    index = dict(zip(dates, _daily_index(dates, levels), strict=True))
    values: list[Decimal | None] = []
    for d in dates:
        now = index[d]
        counted = [(czk, index[then]) for then, czk in invested if then <= d]
        known = [(czk, then) for czk, then in counted if then is not None]
        if now is None or len(known) < len(counted):
            values.append(None)
        else:
            values.append(sum((czk * now / then for czk, then in known), Decimal(0)))
    return Hurdle(values=tuple(values), estimated_from=max(i.month for i in levels) + timedelta(days=1))


def _daily_index(dates: Sequence[date], levels: Sequence[IndexLevel]) -> tuple[Decimal | None, ...]:
    """The index on each day: each month's level sits on its first day, with constant daily growth in between.

    Months after the last published one grow by its month-on-month change. None before the first month.
    """
    points = sorted((i.month, i.level) for i in levels)
    # With a single month there is no change to carry forward, so the index stays flat.
    growth = points[-1][1] / points[-2][1] if len(points) > 1 else Decimal(1)
    while points[-1][0] <= dates[-1]:
        month, level = points[-1]
        points.append((_next_month(month), level * growth))
    months = [month for month, _ in points]
    values: list[Decimal | None] = []
    for d in dates:
        n = bisect_right(months, d) - 1
        if n < 0:
            values.append(None)
            continue
        (start, low), (end, high) = points[n], points[n + 1]
        values.append(low * (high / low) ** (Decimal((d - start).days) / Decimal((end - start).days)))
    return tuple(values)


def _next_month(month: date) -> date:
    return (month + timedelta(days=31)).replace(day=1)


def _czk_per_unit(dates: Sequence[date], currency: str, rates: Sequence[FxRate]) -> tuple[Decimal | None, ...]:
    """The last known CZK rate of `currency` on or before each day; 1 for CZK."""
    if currency == CZK:
        return tuple(Decimal(1) for _ in dates)
    return _last_known(dates, [(r.day, r.czk_per_unit) for r in rates if r.currency == currency])


def _zero_when_not_held(units_held: Sequence[Decimal], values: Sequence[Decimal | None]) -> tuple[Decimal | None, ...]:
    """`values` on the days units are held, else 0: nothing held is worth nothing, even before a price is known."""
    return tuple(value if units else Decimal(0) for units, value in zip(units_held, values, strict=True))


def _last_known(dates: Sequence[date], points: Sequence[tuple[date, Decimal]]) -> tuple[Decimal | None, ...]:
    """The value of the last point on or before each day, so gaps (weekends, holidays) carry the last one forward.

    None until the first point.
    """
    on = dict(points)
    # The last point on or before the first day, so a series has a value from day one when one exists.
    last = max((p for p in points if p[0] <= dates[0]), key=lambda p: p[0], default=None)
    value = last[1] if last else None
    values = []
    for d in dates:
        value = on.get(d, value)
        values.append(value)
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


def _times(series: Sequence[Decimal | None], factors: Sequence[Decimal | None]) -> tuple[Decimal | None, ...]:
    """Day-by-day product; None on a day either is None."""
    return tuple(
        None if value is None or factor is None else value * factor
        for value, factor in zip(series, factors, strict=True)
    )


def _sum(series: Iterable[tuple[Decimal | None, ...]]) -> tuple[Decimal | None, ...]:
    """Day-by-day sum of the series; None on a day any of them is None."""
    return tuple(None if None in day else sum(day, Decimal(0)) for day in zip(*series, strict=True))
