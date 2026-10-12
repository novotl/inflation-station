import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from inflation_station import yahoo
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Callable

SXR7 = "IE00B53QG562"
SXR7_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/SXR7.DE?period1=0&period2=1625097600&interval=1d"
# 1 Jul 2021 09:00 in Frankfurt (CEST), when Xetra opens: the tests' "today".
TODAY_AT_OPEN = 1625122800


def edited(recorded: dict[str, Path], tmp_path: Path, edit: Callable[[dict], None]) -> None:
    """Serve the recorded SXR7 chart after `edit` has changed its parsed JSON in place."""
    chart = json.loads(recorded[SXR7_CHART].read_text(encoding="utf-8"))
    edit(chart)
    recorded[SXR7_CHART] = tmp_path / "chart.json"
    recorded[SXR7_CHART].write_text(json.dumps(chart), encoding="utf-8")


def points(chart: dict) -> tuple[list[int], list[float | None]]:
    result = chart["chart"]["result"][0]
    return result["timestamp"], result["indicators"]["quote"][0]["close"]


def test_each_close_is_stored_on_its_trading_day_in_the_listings_currency() -> None:
    prices = yahoo.price_history(SXR7, "SXR7.DE")

    assert (prices[0].day, prices[-1].day) == (date(2021, 3, 1), date(2021, 6, 30))
    # Recorded as 129.17999267578125, a 32-bit float.
    assert (prices[0].isin, prices[0].price, prices[0].currency) == (SXR7, Decimal("129.18"), "EUR")


def test_todays_point_is_left_out_because_the_market_may_still_be_open(
    recorded: dict[str, Path], tmp_path: Path
) -> None:
    def add_today(chart: dict) -> None:
        stamps, closes = points(chart)
        stamps.append(TODAY_AT_OPEN)
        closes.append(150.0)

    edited(recorded, tmp_path, add_today)

    assert yahoo.price_history(SXR7, "SXR7.DE")[-1].day == date(2021, 6, 30)


def test_a_day_without_a_close_is_skipped(recorded: dict[str, Path], tmp_path: Path) -> None:
    def blank_first_close(chart: dict) -> None:
        points(chart)[1][0] = None

    edited(recorded, tmp_path, blank_first_close)

    assert yahoo.price_history(SXR7, "SXR7.DE")[0].day == date(2021, 3, 2)


def test_points_that_are_not_daily_fail(recorded: dict[str, Path], tmp_path: Path) -> None:
    def weekly(chart: dict) -> None:
        chart["chart"]["result"][0]["meta"]["dataGranularity"] = "1wk"

    edited(recorded, tmp_path, weekly)

    with pytest.raises(InflationStationError, match=r"cannot read the Yahoo Finance chart .*expected daily points"):
        yahoo.price_history(SXR7, "SXR7.DE")


def test_an_error_from_yahoo_fails_naming_the_chart(recorded: dict[str, Path], tmp_path: Path) -> None:
    def error(chart: dict) -> None:
        chart["chart"] = {"result": None, "error": {"code": "Not Found", "description": "No data found"}}

    edited(recorded, tmp_path, error)

    with pytest.raises(InflationStationError, match=r"chart .*SXR7\.DE.*: .*No data found"):
        yahoo.price_history(SXR7, "SXR7.DE")


def test_a_response_that_is_not_a_chart_fails_naming_its_url(recorded: dict[str, Path]) -> None:
    recorded[SXR7_CHART] = Path(__file__).parent / "fixtures" / "yahoo" / "README.md"

    with pytest.raises(InflationStationError, match=r"cannot read the Yahoo Finance chart .*SXR7\.DE"):
        yahoo.price_history(SXR7, "SXR7.DE")
