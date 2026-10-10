"""Downloads daily CZK exchange rates from ČNB (the Czech National Bank), one month of one currency per request."""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station import web
from inflation_station.errors import InflationStationError
from inflation_station.fx_rate import FxRate

if TYPE_CHECKING:
    from collections.abc import Iterable

MONTH_URL = "https://api.cnb.cz/cnbapi/exrates/daily-currency-month?currency={currency}&yearMonth={month}&lang=EN"
# ČNB publishes no rates on weekends and holidays; a week back always reaches a business day.
_LONGEST_GAP = timedelta(days=7)


def months_to_fetch(first_held: date, today: date, stored: Iterable[date]) -> list[date]:
    """The months (as their first days) whose rates are needed to value a holding from `first_held` to `today`.

    Leaves out the months with rates stored already, except the latest of them: it may have been fetched before it
    ended. Every earlier stored month was complete when it was stored, as the latest one is refetched on every run.
    """
    stored_months = {d.replace(day=1) for d in stored}
    latest = max(stored_months, default=None)
    # The rate valid on the first day held may be from the month before, if the month starts with a holiday.
    month = (first_held - _LONGEST_GAP).replace(day=1)
    months = []
    while month <= today:
        if month not in stored_months or month == latest:
            months.append(month)
        month = (month + timedelta(days=31)).replace(day=1)
    return months


def rates(currency: str, month: date) -> list[FxRate]:
    """Every daily rate of `currency` ČNB published in the month starting `month`."""
    url = MONTH_URL.format(currency=currency, month=f"{month:%Y-%m}")
    try:
        response = json.loads(web.fetch(url), parse_float=Decimal, parse_int=Decimal)
        return [
            # ČNB quotes some currencies per 100 units (or more); `amount` says how many.
            FxRate(currency=currency, day=date.fromisoformat(r["validFor"]), czk_per_unit=r["rate"] / r["amount"])
            for r in response["rates"]
            if r["currencyCode"] == currency
        ]
    except (ValueError, KeyError, TypeError, ArithmeticError) as e:
        msg = f"cannot read the ČNB rates {url}: {e!r}"
        raise InflationStationError(msg) from e
