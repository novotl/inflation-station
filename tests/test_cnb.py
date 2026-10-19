import json
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from inflation_station.cnb import months_to_fetch, rates
from inflation_station.errors import InflationStationError
from inflation_station.fx_rate import FxRate

if TYPE_CHECKING:
    from pathlib import Path


def test_a_first_purchase_early_in_january_starts_in_january_itself() -> None:
    assert months_to_fetch(date(2022, 1, 3), today=date(2022, 2, 10), stored=[]) == [
        date(2022, 1, 1),
        date(2022, 2, 1),
    ]


def test_months_run_from_december_into_january() -> None:
    assert months_to_fetch(date(2021, 11, 20), today=date(2022, 1, 5), stored=[]) == [
        date(2021, 11, 1),
        date(2021, 12, 1),
        date(2022, 1, 1),
    ]


def test_with_rates_stored_only_the_latest_stored_month_and_later_are_fetched() -> None:
    stored = [date(2021, 5, 18), date(2021, 5, 31), date(2021, 6, 1), date(2021, 6, 15)]

    assert months_to_fetch(date(2021, 5, 18), today=date(2021, 8, 2), stored=stored) == [
        date(2021, 6, 1),
        date(2021, 7, 1),
        date(2021, 8, 1),
    ]


HUF_RATES = "https://api.cnb.cz/cnbapi/exrates/daily-currency-month?currency=HUF&yearMonth=2021-06&lang=EN"


def huf_response(tmp_path: Path) -> Path:
    """ČNB's response for June 2021's HUF rates, which it quotes per 100 forints, with one day in it."""
    path = tmp_path / "huf.json"
    rate = {"validFor": "2021-06-01", "order": 104, "country": "Hungary", "currency": "forint", "amount": 100}
    path.write_text(json.dumps({"rates": [rate | {"currencyCode": "HUF", "rate": 7.298}]}), encoding="utf-8")
    return path


def test_a_per_100_quote_is_stored_as_published(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[HUF_RATES] = huf_response(tmp_path)

    [rate] = rates("HUF", date(2021, 6, 1))

    assert rate == FxRate(date(2021, 6, 1), "HUF", Decimal(100), "CZK", Decimal("7.298"))
    assert rate.rate == Decimal("0.07298")


def test_an_unknown_currency_is_rejected_before_any_request(recorded: dict[str, Path]) -> None:
    recorded.clear()  # any request fails the test

    with pytest.raises(InflationStationError, match="'HFU' is not an ISO 4217 currency code"):
        rates("HFU", date(2021, 6, 1))
