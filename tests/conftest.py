from datetime import date
from typing import TYPE_CHECKING

import pytest
from recorder import (
    CHART,
    CNB,
    CONSEQ,
    CPI_CSV,
    CSU,
    EUR_MONTHS,
    EUR_RATES,
    EUROSTAT,
    FUND_PAGE,
    HICP_JSON,
    PRICE_HISTORY,
    YAHOO,
)

from inflation_station import clock, web
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# The recorded prices end on this day.
TODAY = date(2021, 7, 1)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "today", lambda: TODAY)


@pytest.fixture
def recorded() -> dict[str, Path | InflationStationError]:
    """The recorded response served for each URL, or the error fetching it raises. Tests may change either."""
    pages = ["ff-world-fund-czk", "franklin-technology-fund-eur", "amundi-funds-us-pioneer-fund-a-eur", "j-t-money-czk"]
    return {
        **{FUND_PAGE + slug: CONSEQ / f"{slug}.html" for slug in pages},
        **{PRICE_HISTORY.format(p): CONSEQ / f"pricehist-{p}.xlsx" for p in (9613, 5485, 8804, 9171)},
        **{EUR_RATES.format(month): CNB / f"eur-{month}.json" for month in EUR_MONTHS},
        **{CHART.format(ticker): YAHOO / f"{ticker}.json" for ticker in ("SXR7.DE", "CSPX.L", "ZPRS.DE")},
        CPI_CSV: CSU / "cen0101ht02.csv",
        HICP_JSON: EUROSTAT / "prc_hicp_minr-cz.json",
    }


@pytest.fixture(autouse=True)
def fake_web(monkeypatch: pytest.MonkeyPatch, recorded: dict[str, Path | InflationStationError]) -> Iterator[None]:
    """Serve recorded responses instead of the network, and fail the test on any URL that wasn't recorded."""
    unrecognised: list[str] = []

    def fetch(url: str) -> bytes:
        if url not in recorded:
            unrecognised.append(url)
            pytest.fail(f"no recorded response for {url}")
        response = recorded[url]
        if isinstance(response, InflationStationError):
            raise response
        return response.read_bytes()

    monkeypatch.setattr(web, "fetch", fetch)
    yield
    # Checked again here in case the code under test swallowed the failure.
    assert not unrecognised, f"no recorded responses for {unrecognised}"
