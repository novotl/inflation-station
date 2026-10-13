"""Turns Purchases, Managed Accounts' ledgers, prices and price indices into a daily timeline of plain data.

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
    """Why a fund priced in `currency` can't be valued when no rates of it are stored."""
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


class Account(NamedTuple):
    """An Account, by its Platform and the Platform's own name or number for it."""

    platform: str
    account_id: str


class Holding(NamedTuple):
    """The units of one fund held in one Account."""

    account: Account
    isin: str


@dataclass(frozen=True)
class AccountTimeline:
    """One Account's series, lined up with the Timeline's `dates`."""

    # Whether it is a Managed Account: one whose money invested is its Deposits, not Purchases (ADR-0002).
    managed: bool
    # The gross CZK of its Purchases, or its Deposits, dated on or before each day.
    amount_invested: tuple[Decimal, ...]
    # The sum of its Holdings' CZK values and its Cash in CZK, in every currency with rates; None when none of its
    # Holdings can be valued.
    value: tuple[Decimal | None, ...] | None
    # The inflation hurdle of its Purchases or Deposits, by price index series.
    hurdles: Mapping[str, Hurdle]
    # Its Cash by currency, for every currency in its ledger, as `Timeline.cash`.
    cash: Mapping[str, tuple[Decimal, ...]]


@dataclass(frozen=True)
class Timeline:
    """One entry per day, from the first Purchase or ledger entry to "today". Every series lines up with `dates`.

    A value is None on a day it can't be known: units are held, but no price is known yet.
    """

    dates: tuple[date, ...]
    # The gross CZK of Purchases plus the Deposits dated on or before each day; fees count as invested, so they count
    # against the return.
    amount_invested: tuple[Decimal, ...]
    # Every Account purchased in or with a ledger, by Account.
    accounts: Mapping[Account, AccountTimeline]
    # `amount_invested` by Holding, counting only that Holding's Purchases, for every Holding outside Managed Accounts:
    # a Holding in a Managed Account has nothing invested in it (ADR-0002).
    holding_amount_invested: Mapping[Holding, tuple[Decimal, ...]]
    # The latest fund name by ISIN, for every fund purchased or held.
    fund_names: Mapping[str, str]
    # Units held by Holding, for every fund purchased or held in each Account: the units of its Purchases traded, and
    # of its buys less its sells in Managed Accounts, on or before each day.
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
    # The sum of `holding_values`; None when no fund can be valued.
    portfolio_value: tuple[Decimal | None, ...] | None
    # Why each fund that can't be valued couldn't be, by ISIN.
    not_valued: Mapping[str, str]
    # The inflation hurdle by price index series, for every series with index levels.
    hurdles: Mapping[str, Hurdle]
    # `hurdles` by Holding, counting only that Holding's Purchases, for the same Holdings as `holding_amount_invested`.
    holding_hurdles: Mapping[Holding, Mapping[str, Hurdle]]
    # Cash in Managed Accounts by currency, for every currency in their ledgers: the sum of the entries dated on or
    # before each day. Negative when a hedging leg goes out a day before the other comes in.
    cash: Mapping[str, tuple[Decimal, ...]]


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

    managed = {_account(e) for e in ledger}
    holdings = sorted({Holding(_account(p), p.isin) for p in purchases} | {_holding(e) for e in ledger if e.isin})
    purchased = {h: [p for p in purchases if Holding(_account(p), p.isin) == h] for h in holdings}
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

    # Fund prices and what they're in, by ISIN: a fund held in two Accounts is priced once.
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

    levels_by_series = {
        series: [i for i in index_levels if i.series == series] for series in sorted({i.series for i in index_levels})
    }
    invested_in = {
        a: [(p.trade_date, p.gross_czk) for p in purchases if _account(p) == a]
        + [(e.day, e.amount) for e in ledger if e.kind == DEPOSIT and _account(e) == a]
        for a in sorted({_account(p) for p in purchases} | managed)
    }
    accounts = {}
    for a, invested in invested_in.items():
        entries = [e for e in ledger if _account(e) == a]
        cash = _cash(dates, entries)
        valued = [values for h, values in holding_values.items() if h.account == a]
        unvalued = any(h.account == a and h not in holding_values for h in holdings)
        parts = valued + [_times(cash[c], czk_rates[c]) for c in cash if c in czk_rates]
        accounts[a] = AccountTimeline(
            managed=a in managed,
            amount_invested=_running_total(dates, invested),
            value=None if (unvalued and not valued) or not parts else _sum(parts),
            hurdles={series: _hurdle(dates, invested, levels) for series, levels in levels_by_series.items()},
            cash=cash,
        )
    every_investment = [i for invested in invested_in.values() for i in invested]
    bought_in = {h: [(p.trade_date, p.gross_czk) for p in purchased[h]] for h in holdings if h.account not in managed}
    return Timeline(
        dates=dates,
        amount_invested=_running_total(dates, every_investment),
        accounts=accounts,
        holding_amount_invested={h: _running_total(dates, bought) for h, bought in bought_in.items()},
        # A fund's name on a Platform where you pick the funds wins over its ticker in a Managed Account.
        fund_names=dict(sorted((held_fund_names(ledger) | fund_names(purchases)).items())),
        units_held=units_held,
        holding_values=holding_values,
        holding_currency_values=holding_currency_values,
        fund_currencies=fund_currencies,
        priced_in=priced_in,
        portfolio_value=_sum(list(holding_values.values())) if holding_values else None,
        not_valued=not_valued,
        hurdles={series: _hurdle(dates, every_investment, levels) for series, levels in levels_by_series.items()},
        holding_hurdles={
            h: {series: _hurdle(dates, bought, levels) for series, levels in levels_by_series.items()}
            for h, bought in bought_in.items()
        },
        cash=_cash(dates, ledger),
    )


def _account(row: Purchase | LedgerEntry) -> Account:
    return Account(row.platform, row.account_id)


def _holding(entry: LedgerEntry) -> Holding:
    return Holding(_account(entry), entry.isin)


def _cash(dates: Sequence[date], ledger: Sequence[LedgerEntry]) -> dict[str, tuple[Decimal, ...]]:
    """Cash by currency, for every currency in `ledger`: the sum of its entries dated on or before each day."""
    return {
        currency: _running_total(dates, [(e.day, e.amount) for e in ledger if e.currency == currency])
        for currency in sorted({e.currency for e in ledger})
    }


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
