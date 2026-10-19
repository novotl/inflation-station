"""Turns Purchases, Managed Portfolios' ledgers, prices and price indices into a daily timeline of plain data.

No I/O: all of it is passed in.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

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


class Portfolio(NamedTuple):
    """A Portfolio, by its Platform and the Platform's own name or number for it."""

    platform: str
    portfolio_id: str


class Holding(NamedTuple):
    """The units of one fund held in one Portfolio."""

    portfolio: Portfolio
    isin: str


@dataclass(frozen=True)
class PortfolioTimeline:
    """One Portfolio's series, lined up with the Timeline's `dates`."""

    # Whether it is a Managed Portfolio: one whose money invested is its Deposits, not Purchases (ADR-0002).
    managed: bool
    # The gross CZK of its Purchases, or its Deposits, dated on or before each day.
    amount_invested: tuple[Decimal, ...]
    # The sum of the CZK values of its Holdings and its Cash that can be valued, as `Timeline.whole_portfolio_value`;
    # None when none of them can be.
    value: tuple[Decimal | None, ...] | None
    # The inflation hurdle of its Purchases or Deposits, by price index series.
    hurdles: Mapping[str, Hurdle]
    # Why its Cash in each currency left out of `value` couldn't be valued, by currency.
    cash_not_valued: Mapping[str, str]


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first Purchase or ledger entry to "today". Every series lines up with `dates`.

    A value is None on a day it can't be known: units are held, but no price is known yet.
    """

    dates: tuple[date, ...]
    # The gross CZK of Purchases plus the Deposits dated on or before each day; fees count as invested, so they count
    # against the return.
    amount_invested: tuple[Decimal, ...]
    # Every Portfolio purchased in or with a ledger, by Portfolio.
    portfolios: Mapping[Portfolio, PortfolioTimeline]
    # `amount_invested` by Holding, counting only that Holding's Purchases, for every Holding outside Managed
    # Portfolios: a Holding in a Managed Portfolio has nothing invested in it (ADR-0002).
    holding_amount_invested: Mapping[Holding, tuple[Decimal, ...]]
    # The latest fund name by ISIN, for every fund purchased or held.
    fund_names: Mapping[str, str]
    # Units held by Holding, for every fund purchased or held in each Portfolio: the units of its Purchases traded, and
    # of its buys less its sells in Managed Portfolios, on or before each day.
    units_held: Mapping[Holding, tuple[Decimal, ...]]
    # CZK value by Holding, for the Holdings of funds that can be valued: units held x the last known price on or
    # before the day, x the last known CZK rate on or before the day for funds not priced in CZK.
    holding_values: Mapping[Holding, tuple[Decimal | None, ...]]
    # Value in the fund's own currency by Holding, for the same Holdings as `holding_values`: units held x the last
    # known price on or before the day.
    holding_currency_values: Mapping[Holding, tuple[Decimal | None, ...]]
    # The currency each fund that can be valued is priced in, by ISIN.
    fund_currencies: Mapping[str, str]
    # What each fund is priced in, by ISIN, for every fund purchased or held: the currencies of its prices, or the
    # currency of its latest Purchase (else of its latest buy or sell) when it has none.
    priced_in: Mapping[str, str]
    # The sum of `holding_values` and `cash_values`; None when no fund or Cash can be valued.
    whole_portfolio_value: tuple[Decimal | None, ...] | None
    # Why each fund that can't be valued couldn't be, by ISIN.
    not_valued: Mapping[str, str]
    # The inflation hurdle by price index series, for every series with index levels.
    hurdles: Mapping[str, Hurdle]
    # `hurdles` by Holding, counting only that Holding's Purchases, for the same Holdings as `holding_amount_invested`.
    holding_hurdles: Mapping[Holding, Mapping[str, Hurdle]]
    # Cash in Managed Portfolios by currency, for every currency in their ledgers: the sum of the entries dated on or
    # before each day. Negative when a hedging leg goes out a day before the other comes in.
    cash: Mapping[str, tuple[Decimal, ...]]
    # CZK value of `cash` by currency, for the currencies that can be valued: the Cash x the last known CZK rate on
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

    # Only Managed Portfolios have ledgers.
    managed = {_portfolio(e) for e in ledger}
    holdings = sorted({Holding(_portfolio(p), p.isin) for p in purchases} | {_holding(e) for e in ledger if e.isin})
    purchased = {h: [p for p in purchases if Holding(_portfolio(p), p.isin) == h] for h in holdings}
    traded = {h: [e for e in ledger if e.isin and _holding(e) == h] for h in holdings}
    units_held = {
        h: _running_total(
            dates, [(p.trade_date, p.units) for p in purchased[h]] + [(e.day, e.units) for e in traded[h]]
        )
        for h in holdings
    }
    czk_rates = {
        currency: _last_known(dates, [(r.day, r.czk_per_unit) for r in rates if r.currency == currency])
        for currency in sorted({r.currency for r in rates})
    } | {CZK: tuple(Decimal(1) for _ in dates)}

    # Fund prices and what they're in, by ISIN: a fund held in two Portfolios is priced once.
    fund_currencies: dict[str, str] = {}
    not_valued: dict[str, str] = {}
    priced_in: dict[str, str] = {}
    unit_prices: dict[str, tuple[Decimal | None, ...]] = {}
    for isin in sorted({h.isin for h in holdings}):
        fund_prices = [p for p in prices if p.isin == isin]
        currencies = sorted({p.currency for p in fund_prices})
        bought = [p for p in purchases if p.isin == isin]
        if currencies:
            priced_in[isin] = ", ".join(currencies)
        elif bought:
            priced_in[isin] = max(bought, key=lambda p: p.trade_date).unit_price_currency
        else:
            priced_in[isin] = max((e for e in ledger if e.isin == isin), key=lambda e: e.day).currency
        if not fund_prices:
            not_valued[isin] = NO_PRICES
        elif len(currencies) > 1:
            not_valued[isin] = f"priced in {priced_in[isin]}"
        elif currencies[0] not in czk_rates:
            not_valued[isin] = no_rates(currencies[0])
        else:
            fund_currencies[isin] = currencies[0]
            unit_prices[isin] = _last_known(dates, [(p.day, p.price) for p in fund_prices])
    holding_currency_values: dict[Holding, tuple[Decimal | None, ...]] = {}
    holding_values: dict[Holding, tuple[Decimal | None, ...]] = {}
    for h, units in units_held.items():
        if h.isin in unit_prices:
            holding_currency_values[h] = _zero_when_not_held(units, _times(units, unit_prices[h.isin]))
            czk_per_unit = czk_rates[fund_currencies[h.isin]]
            holding_values[h] = _zero_when_not_held(units, _times(holding_currency_values[h], czk_per_unit))
    cash = _cash(dates, ledger)
    cash_values, cash_not_valued = _cash_values(cash, czk_rates)
    whole_portfolio_parts = [*holding_values.values(), *cash_values.values()]

    levels_by_series = {
        series: [i for i in index_levels if i.series == series] for series in sorted({i.series for i in index_levels})
    }
    invested_in = {
        a: [(p.trade_date, p.gross_czk) for p in purchases if _portfolio(p) == a]
        + [(e.day, e.amount) for e in ledger if e.kind == DEPOSIT and _portfolio(e) == a]
        for a in sorted({_portfolio(p) for p in purchases} | managed)
    }
    portfolios = {}
    for a, invested in invested_in.items():
        portfolio_cash = _cash(dates, [e for e in ledger if _portfolio(e) == a])
        parts = [values for h, values in holding_values.items() if h.portfolio == a]
        portfolio_cash_values, portfolio_cash_not_valued = _cash_values(portfolio_cash, czk_rates)
        parts += portfolio_cash_values.values()
        portfolios[a] = PortfolioTimeline(
            managed=a in managed,
            amount_invested=_running_total(dates, invested),
            value=_sum(parts) if parts else None,
            hurdles=_hurdles(dates, invested, levels_by_series),
            cash_not_valued=portfolio_cash_not_valued,
        )
    every_investment = [i for invested in invested_in.values() for i in invested]
    bought_in = {h: [(p.trade_date, p.gross_czk) for p in purchased[h]] for h in holdings if h.portfolio not in managed}
    return Timeline(
        dates=dates,
        amount_invested=_running_total(dates, every_investment),
        portfolios=portfolios,
        holding_amount_invested={h: _running_total(dates, bought) for h, bought in bought_in.items()},
        fund_names=all_fund_names(purchases, ledger),
        units_held=units_held,
        holding_values=holding_values,
        holding_currency_values=holding_currency_values,
        fund_currencies=fund_currencies,
        priced_in=priced_in,
        whole_portfolio_value=_sum(whole_portfolio_parts) if whole_portfolio_parts else None,
        not_valued=not_valued,
        hurdles=_hurdles(dates, every_investment, levels_by_series),
        holding_hurdles={h: _hurdles(dates, bought, levels_by_series) for h, bought in bought_in.items()},
        cash=cash,
        cash_values=cash_values,
        cash_value=_sum(cash_values.values()) if cash_values else None,
        cash_not_valued=cash_not_valued,
    )


def all_fund_names(purchases: Iterable[Purchase], ledger: Iterable[LedgerEntry]) -> dict[str, str]:
    """The name of every fund purchased or held, by ISIN, sorted by ISIN."""
    # A fund's name on a Platform where you pick the funds wins over its ticker in a Managed Portfolio.
    return dict(sorted((held_fund_names(ledger) | fund_names(purchases)).items()))


def _portfolio(row: Purchase | LedgerEntry) -> Portfolio:
    """The Portfolio a Purchase or ledger entry is in."""
    return Portfolio(row.platform, row.portfolio_id)


def _holding(entry: LedgerEntry) -> Holding:
    """The Holding a buy or sell moves the units of."""
    return Holding(_portfolio(entry), entry.isin)


def _cash(dates: Sequence[date], ledger: Sequence[LedgerEntry]) -> dict[str, tuple[Decimal, ...]]:
    """Cash by currency, for every currency in `ledger`: the sum of its entries dated on or before each day."""
    return {
        currency: _running_total(dates, [(e.day, e.amount) for e in ledger if e.currency == currency])
        for currency in sorted({e.currency for e in ledger})
    }


def _cash_values(
    cash: Mapping[str, Sequence[Decimal]], czk_rates: Mapping[str, Sequence[Decimal | None]]
) -> tuple[dict[str, tuple[Decimal | None, ...]], dict[str, str]]:
    """CZK value of `cash` by currency, for the currencies with rates; and why each of the others isn't valued."""
    # Taken as it is, so negative Cash counts against the value.
    values = {
        c: _zero_when_not_held(amounts, _times(amounts, czk_rates[c])) for c, amounts in cash.items() if c in czk_rates
    }
    return values, {c: no_rates(c) for c in cash if c not in czk_rates}


def _hurdles(
    dates: Sequence[date],
    invested: Sequence[tuple[date, Decimal]],
    levels_by_series: Mapping[str, Sequence[IndexLevel]],
) -> dict[str, Hurdle]:
    """`_hurdle` by price index series."""
    return {series: _hurdle(dates, invested, levels) for series, levels in levels_by_series.items()}


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


def _zero_when_not_held(held: Sequence[Decimal], values: Sequence[Decimal | None]) -> tuple[Decimal | None, ...]:
    """`values` on the days some units or Cash are held, else 0: nothing held is worth nothing, even before a price or
    rate is known.
    """
    return tuple(value if amount else Decimal(0) for amount, value in zip(held, values, strict=True))


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
