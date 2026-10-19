"""Turns imported rows, prices and price indices into a daily timeline of plain data. No I/O: all of it is passed in.

Until every Platform imports its Deposits, a Portfolio with none has the CZK it paid out of Cash as its amount invested
and no Cash; one with Deposits has them as its amount invested, and Cash.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from inflation_station.currency import CZK
from inflation_station.domain import CONVERSION_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from inflation_station.domain import Fund, Portfolio, Purchase, Rows, Sale
    from inflation_station.fund_price import FundPrice
    from inflation_station.fx_rate import FxRate
    from inflation_station.price_index import IndexLevel

NO_PRICES = "no prices stored"


def no_rates(currency: str) -> str:
    """Why a fund priced in, or Cash held in, `currency` can't be valued when no rates of it are stored."""
    return f"no {currency} rates stored"


@dataclass(frozen=True)
class Hurdle:
    """What the money invested would need to be worth on each day to keep its purchasing power, by one price index.

    A value is None on a day the index is unknown for a Purchase, Fee or Deposit counted that day.
    """

    # Σ CZK x I(day) / I(date), over the CZK of Purchases, the Fees and the Deposits dated on or before the day.
    values: tuple[Decimal | None, ...]
    # The first day whose index leans on an estimated month: the day after the last published month starts.
    estimated_from: date


class Holding(NamedTuple):
    """The units of one Fund held in one Portfolio."""

    portfolio: Portfolio
    fund: Fund

    @property
    def isin(self) -> str:
        return self.fund.isin


@dataclass(frozen=True)
class PortfolioTimeline:
    """One Portfolio's series, lined up with the Timeline's `dates`."""

    # Whether it has Deposits, so they are its amount invested (ADR-0002) and it has Cash.
    managed: bool
    # The CZK of its Deposits, or without any the CZK it paid out of Cash, dated on or before each day.
    amount_invested: tuple[Decimal, ...]
    # The sum of the CZK values of its Holdings and its Cash that can be valued, as `Timeline.whole_portfolio_value`;
    # None when none of them can be.
    value: tuple[Decimal | None, ...] | None
    # The inflation hurdle of its amount invested, by price index series.
    hurdles: Mapping[str, Hurdle]
    # Why its Cash in each currency left out of `value` couldn't be valued, by currency.
    cash_not_valued: Mapping[str, str]


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first imported row to "today". Every series lines up with `dates`.

    A value is None on a day it can't be known: units are held, but no price is known yet.
    """

    dates: tuple[date, ...]
    # The sum of every Portfolio's `amount_invested`.
    amount_invested: tuple[Decimal, ...]
    # Every Portfolio with imported rows, by Portfolio.
    portfolios: Mapping[Portfolio, PortfolioTimeline]
    # `amount_invested` by Holding, for every Holding in a Portfolio without Deposits: the CZK paid for its Purchases,
    # with the Fees and Conversions that share their source rows. A Holding in a Portfolio with Deposits has nothing
    # invested in it (ADR-0002).
    holding_amount_invested: Mapping[Holding, tuple[Decimal, ...]]
    # The latest fund name by ISIN, for every fund purchased or held.
    fund_names: Mapping[str, str]
    # Units held by Holding, for every fund bought or sold in each Portfolio: its Purchases' units less its Sales', on
    # or before each day.
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
    # currency of its latest Purchase or Sale when it has none.
    priced_in: Mapping[str, str]
    # The sum of `holding_values` and `cash_values`; None when no fund or Cash can be valued.
    whole_portfolio_value: tuple[Decimal | None, ...] | None
    # Why each fund that can't be valued couldn't be, by ISIN.
    not_valued: Mapping[str, str]
    # The inflation hurdle by price index series, for every series with index levels.
    hurdles: Mapping[str, Hurdle]
    # `hurdles` by Holding, counting only that Holding's Purchases and Fees, for the same Holdings as
    # `holding_amount_invested`.
    holding_hurdles: Mapping[Holding, Mapping[str, Hurdle]]
    # Cash in Portfolios with Deposits by currency, for every currency moved in them: what came in less what went out,
    # on or before each day.
    cash: Mapping[str, tuple[Decimal, ...]]
    # CZK value of `cash` by currency, for the currencies that can be valued: the Cash x the last known CZK rate on
    # or before the day, for currencies other than CZK.
    cash_values: Mapping[str, tuple[Decimal | None, ...]]
    # The sum of `cash_values`; None when no Cash can be valued.
    cash_value: tuple[Decimal | None, ...] | None
    # Why the Cash in each currency left out of `cash_values` couldn't be valued, by currency.
    cash_not_valued: Mapping[str, str]


def timeline(
    rows: Rows,
    *,
    prices: Sequence[FundPrice] = (),
    rates: Sequence[FxRate] = (),
    index_levels: Sequence[IndexLevel] = (),
    today: date,
) -> Timeline:
    """`rows` must not be empty: with nothing imported there is no first day."""
    first = min(r.day for r in [*rows.deposits, *rows.purchases, *rows.sales, *rows.fees, *rows.conversions])
    dates = tuple(first + timedelta(days=n) for n in range((today - first).days + 1))

    funds = rows.funds()
    deposited = {d.portfolio for d in rows.deposits}
    bought_or_sold = [*rows.purchases, *rows.sales]
    holdings = sorted({Holding(t.portfolio, funds[t.fund.isin]) for t in bought_or_sold}, key=_holding_order)
    units_held = {
        h: _running_total(
            dates,
            [(p.day, p.units) for p in rows.purchases if _is_in(p, h)]
            + [(s.day, -s.units) for s in rows.sales if _is_in(s, h)],
        )
        for h in holdings
    }
    to_czk = [r for r in rates if r.to_currency == CZK]
    czk_rates = {
        currency: _last_known(dates, [(r.day, r.rate) for r in to_czk if r.from_currency == currency])
        for currency in sorted({r.from_currency for r in to_czk})
    } | {CZK: tuple(Decimal(1) for _ in dates)}

    # Fund prices and what they're in, by ISIN: a fund held in two Portfolios is priced once.
    fund_currencies: dict[str, str] = {}
    not_valued: dict[str, str] = {}
    priced_in: dict[str, str] = {}
    unit_prices: dict[str, tuple[Decimal | None, ...]] = {}
    for isin in funds:
        fund_prices = [p for p in prices if p.isin == isin]
        currencies = sorted({p.currency for p in fund_prices})
        if currencies:
            priced_in[isin] = ", ".join(currencies)
        else:
            priced_in[isin] = max((t for t in bought_or_sold if t.fund.isin == isin), key=lambda t: t.day).currency
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
    moves = _cash_moves(rows, deposited)
    cash = _cash(dates, moves)
    cash_values, cash_not_valued = _cash_values(cash, czk_rates)
    whole_portfolio_parts = [*holding_values.values(), *cash_values.values()]

    levels_by_series = {
        series: [i for i in index_levels if i.series == series] for series in sorted({i.series for i in index_levels})
    }
    every_portfolio = {r.portfolio for r in [*rows.deposits, *bought_or_sold, *rows.fees, *rows.conversions]}
    invested_in = {
        a: [(d.day, d.amount) for d in rows.deposits if d.portfolio == a] if a in deposited else _paid_in_czk(rows, a)
        for a in sorted(every_portfolio, key=_portfolio_order)
    }
    portfolios = {}
    for a, invested in invested_in.items():
        portfolio_cash = _cash(dates, [m for m in moves if m.portfolio == a])
        parts = [values for h, values in holding_values.items() if h.portfolio == a]
        portfolio_cash_values, portfolio_cash_not_valued = _cash_values(portfolio_cash, czk_rates)
        parts += portfolio_cash_values.values()
        portfolios[a] = PortfolioTimeline(
            managed=a in deposited,
            amount_invested=_running_total(dates, invested),
            value=_sum(parts) if parts else None,
            hurdles=_hurdles(dates, invested, levels_by_series),
            cash_not_valued=portfolio_cash_not_valued,
        )
    every_investment = [i for invested in invested_in.values() for i in invested]
    bought_in = {
        h: [paid for p in rows.purchases if _is_in(p, h) for paid in _paid_for(rows, p)]
        for h in holdings
        if h.portfolio not in deposited
    }
    return Timeline(
        dates=dates,
        amount_invested=_running_total(dates, every_investment),
        portfolios=portfolios,
        holding_amount_invested={h: _running_total(dates, bought) for h, bought in bought_in.items()},
        fund_names={isin: fund.name for isin, fund in funds.items()},
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


def _portfolio_order(portfolio: Portfolio) -> tuple[str, str]:
    return (portfolio.platform, portfolio.key)


def _holding_order(holding: Holding) -> tuple[str, str, str]:
    return (*_portfolio_order(holding.portfolio), holding.isin)


def _is_in(row: Purchase | Sale, holding: Holding) -> bool:
    """Whether a Purchase or Sale is of a Holding, whatever its Fund was named in it."""
    return (row.portfolio, row.fund.isin) == (holding.portfolio, holding.isin)


class _CashMove(NamedTuple):
    """Cash coming in (+) or going out (-) of a Portfolio."""

    portfolio: Portfolio
    day: date
    amount: Decimal
    currency: str


def _cash_moves(rows: Rows, portfolios: set[Portfolio]) -> list[_CashMove]:
    """Every move of Cash in `portfolios`."""
    moves = (
        [_CashMove(d.portfolio, d.day, d.amount, d.currency) for d in rows.deposits]
        + [_CashMove(p.portfolio, p.day, -p.amount, p.currency) for p in rows.purchases]
        + [_CashMove(s.portfolio, s.day, s.amount, s.currency) for s in rows.sales]
        + [_CashMove(f.portfolio, f.day, -f.amount, f.currency) for f in rows.fees]
        + [_CashMove(c.portfolio, c.day, -c.from_amount, c.from_currency) for c in rows.conversions]
        + [_CashMove(c.portfolio, c.day, c.to_amount, c.to_currency) for c in rows.conversions]
    )
    return [m for m in moves if m.portfolio in portfolios]


def _cash(dates: Sequence[date], moves: Sequence[_CashMove]) -> dict[str, tuple[Decimal, ...]]:
    """Cash by currency, for every currency in `moves`: the sum of the moves dated on or before each day."""
    return {
        currency: _running_total(dates, [(m.day, m.amount) for m in moves if m.currency == currency])
        for currency in sorted({m.currency for m in moves})
    }


def _paid_in_czk(rows: Rows, portfolio: Portfolio) -> list[tuple[date, Decimal]]:
    """The (day, CZK) of every CZK the Portfolio paid out of Cash: for Purchases, Fees and Conversions."""
    return (
        [(p.day, p.amount) for p in rows.purchases if p.portfolio == portfolio and p.currency == CZK]
        + [(f.day, f.amount) for f in rows.fees if f.portfolio == portfolio and f.currency == CZK]
        + [(c.day, c.from_amount) for c in rows.conversions if c.portfolio == portfolio and c.from_currency == CZK]
    )


def _paid_for(rows: Rows, purchase: Purchase) -> list[tuple[date, Decimal]]:
    """The (day, CZK) paid for a Purchase: itself if in CZK, else the Conversion paying for it; and its Fee."""
    paid = [(purchase.day, purchase.amount)] if purchase.currency == CZK else []
    paid += [
        (c.day, c.from_amount)
        for c in rows.conversions
        if (c.portfolio, c.source_row_id) == (purchase.portfolio, purchase.source_row_id + CONVERSION_SUFFIX)
        and c.from_currency == CZK
    ]
    paid += [
        (f.day, f.amount)
        for f in rows.fees
        if (f.portfolio, f.source_row_id) == (purchase.portfolio, purchase.source_row_id) and f.currency == CZK
    ]
    return paid


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
    """`invested` is each Purchase's, Fee's or Deposit's (date, CZK). `levels` must not be empty, and must be one
    series' levels for consecutive months.
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
