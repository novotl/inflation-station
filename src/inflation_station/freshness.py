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

    Series with nothing stored are left out. `fund_names` names the funds by ISIN; prices of other funds are ignored.
    """
    warnings = []
    last_price = _last((p.isin, p.day) for p in prices)
    for isin, name in fund_names.items():
        last = last_price.get(isin)
        if last is not None and _business_days(last, today) > MAX_BUSINESS_DAYS:
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


def _business_days(after: date, until: date) -> int:
    """The Mondays to Fridays after `after`, up to and including `until`."""
    return sum((after + timedelta(days=n)).weekday() < SATURDAY for n in range(1, (until - after).days + 1))


def _months_between(since: date, until: date) -> int:
    """How many months `until`'s month is after `since`'s."""
    return (until.year - since.year) * 12 + until.month - since.month
