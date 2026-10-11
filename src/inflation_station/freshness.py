"""Finds the stored series whose last point is too old for the chart's latest days. No I/O: all of it is passed in."""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from inflation_station.price_index import NAMES

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from inflation_station.fund_price import FundPrice
    from inflation_station.fx_rate import FxRate
    from inflation_station.price_index import IndexLevel

# Business days (Monday to Friday) after its last point before a daily series is out of date: enough for a holiday
# or a late publication, short enough to notice a forgotten fetch within a week or so.
MAX_BUSINESS_DAYS = 5
# Months between a price index's last month and today's before it is out of date. Both indices publish a month by the
# end of the next, so on any day of August June should be out, and May alone is two months behind.
MAX_MONTHS = 2
# Days between a fund's last two prices beyond which it is priced monthly, and judged by MAX_MONTHS like an index:
# well over a daily fund's longest holiday gap, well under a month.
MONTHLY_GAP_DAYS = 20
# date.weekday() of Saturday; Monday is 0.
SATURDAY = 5


def out_of_date(
    *,
    prices: Iterable[FundPrice] = (),
    rates: Iterable[FxRate] = (),
    index_levels: Iterable[IndexLevel] = (),
    fund_names: Mapping[str, str],
    today: date,
) -> list[str]:
    """A warning for each fund's prices, each currency's rates and each price index series that is out of date.

    A fund whose last two prices are more than MONTHLY_GAP_DAYS apart is priced monthly and judged by its last price's
    month, like a price index. Series with nothing stored are left out. `fund_names` names the funds by ISIN; prices of
    other funds are ignored.
    """
    warnings = []
    last_prices = _last_two((p.isin, p.day) for p in prices)
    for isin, name in fund_names.items():
        if isin not in last_prices:
            continue
        last, previous = last_prices[isin]
        if previous is not None and (last - previous).days > MONTHLY_GAP_DAYS:
            too_old = _months_between(last, today) > MAX_MONTHS
        else:
            too_old = _business_days(last, today) > MAX_BUSINESS_DAYS
        if too_old:
            warnings.append(f"{name} ({isin}) prices end on {last}; run inflation-station fetch-prices")
    for currency, last in sorted(_last((r.currency, r.day) for r in rates).items()):
        if _business_days(last, today) > MAX_BUSINESS_DAYS:
            warnings.append(f"{currency} rates end on {last}; run inflation-station fetch-fx")
    for series, last in sorted(_last((i.series, i.month) for i in index_levels).items()):
        if _months_between(last, today) > MAX_MONTHS:
            warnings.append(f"{NAMES[series]} ends with {last:%Y-%m}; run inflation-station fetch-cpi")
    return warnings


def _last(points: Iterable[tuple[str, date]]) -> dict[str, date]:
    """The latest day by key."""
    last: dict[str, date] = {}
    for key, day in points:
        last[key] = max(day, last.get(key, day))
    return last


def _last_two(points: Iterable[tuple[str, date]]) -> dict[str, tuple[date, date | None]]:
    """The latest day by key, and the one before it, if any."""
    last_two: dict[str, tuple[date, date | None]] = {}
    for key, day in points:
        if key not in last_two:
            last_two[key] = (day, None)
            continue
        latest, previous = last_two[key]
        if day > latest:
            last_two[key] = (day, latest)
        elif day < latest and (previous is None or day > previous):
            last_two[key] = (latest, day)
    return last_two


def _business_days(after: date, until: date) -> int:
    """The Mondays to Fridays after `after`, up to and including `until`."""
    return sum((after + timedelta(days=n)).weekday() < SATURDAY for n in range(1, (until - after).days + 1))


def _months_between(since: date, until: date) -> int:
    """How many months `until`'s month is after `since`'s."""
    return (until.year - since.year) * 12 + until.month - since.month
