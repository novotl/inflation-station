"""Downloads the daily closes of exchange-traded funds from Yahoo Finance's chart API."""

import json
import tomllib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from inflation_station import clock, web
from inflation_station.currency import code as currency_code
from inflation_station.errors import InflationStationError
from inflation_station.fund_price import FundPrice

# The hand-edited mapping from ISIN to Yahoo Finance ticker.
TICKERS = Path(__file__).parent / "yahoo_funds.toml"
DAILY = "1d"
# Every daily point from the listing's first day up to `period2`: `range=max` would thin out to weekly or monthly ones.
CHART = f"https://query1.finance.yahoo.com/v8/finance/chart/{{}}?period1=0&period2={{}}&interval={DAILY}"
# Closes are 32-bit floats (143.72 comes as 143.72000122070312), good to about 7 significant digits.
_SIGNIFICANT_DIGITS = 7


def tickers() -> dict[str, str]:
    """The Yahoo Finance ticker of each fund listed in TICKERS, by ISIN."""
    return tomllib.loads(TICKERS.read_text(encoding="utf-8"))


def price_history(isin: str, ticker: str) -> list[FundPrice]:
    """Every daily close Yahoo has for `ticker` before today, in the listing's currency.

    Today's point is left out: until the market closes it is the latest trade, and stored prices are never replaced.
    """
    today = clock.today()
    midnight = datetime(today.year, today.month, today.day, tzinfo=UTC)
    url = CHART.format(quote(ticker), int(midnight.timestamp()))
    try:
        return _read_chart(isin, json.loads(web.fetch(url)), today)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
        msg = f"cannot read the Yahoo Finance chart {url}: {e}"
        raise InflationStationError(msg) from e


def _read_chart(isin: str, chart: dict, today: date) -> list[FundPrice]:
    if error := chart["chart"]["error"]:
        msg = f"{error['code']}: {error['description']}"
        raise ValueError(msg)
    result = chart["chart"]["result"][0]
    meta = result["meta"]
    if meta["dataGranularity"] != DAILY:
        msg = f"expected daily points, got {meta['dataGranularity']!r}"
        raise ValueError(msg)
    # Each point is stamped at the day's market open, hours away from midnight, so the offset now (summer or winter
    # time) puts it on the right day either way.
    offset = timedelta(seconds=meta["gmtoffset"])
    closes = result["indicators"]["quote"][0]["close"]
    prices = []
    for stamp, close in zip(result.get("timestamp", []), closes, strict=True):
        day = (datetime.fromtimestamp(stamp, UTC) + offset).date()
        # A day without trades has no close.
        if close is None or day >= today:
            continue
        price = Decimal(f"{close:.{_SIGNIFICANT_DIGITS}g}")
        prices.append(FundPrice(isin=isin, day=day, price=price, currency=currency_code(meta["currency"])))
    return prices
