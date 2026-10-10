from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from inflation_station import clock, web

if TYPE_CHECKING:
    from collections.abc import Iterator

CONSEQ = Path(__file__).parent / "fixtures" / "conseq"
CNB = Path(__file__).parent / "fixtures" / "cnb"
CSU = Path(__file__).parent / "fixtures" / "csu"
FUND_PAGE = "https://www.conseq.cz/investice/prehled-fondu/"
PRICE_HISTORY = "https://www.conseq.cz/Conseq/Pricehist.ashx?productid={}&culture=cs-CZ"
EUR_RATES = "https://api.cnb.cz/cnbapi/exrates/daily-currency-month?currency=EUR&yearMonth={}&lang=EN"
CSU_CPI = "https://data.csu.gov.cz/api/dotaz/v1/data/vybery/CEN0101HT02?format=CSV"
# The months of EUR rates recorded: from the first EUR Purchase in the J&T fixture to "today".
EUR_MONTHS = ("2021-05", "2021-06", "2021-07")
# The recorded prices end on this day.
TODAY = date(2021, 7, 1)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "today", lambda: TODAY)


@pytest.fixture
def recorded() -> dict[str, Path]:
    """The recorded response served for each URL. Tests may change it to serve something else."""
    pages = ["ff-world-fund-czk", "franklin-technology-fund-eur", "amundi-funds-us-pioneer-fund-a-eur", "j-t-money-czk"]
    return {
        **{FUND_PAGE + slug: CONSEQ / f"{slug}.html" for slug in pages},
        **{PRICE_HISTORY.format(p): CONSEQ / f"pricehist-{p}.xlsx" for p in (9613, 5485, 8804, 9171)},
        **{EUR_RATES.format(month): CNB / f"eur-{month}.json" for month in EUR_MONTHS},
        CSU_CPI: CSU / "cen0101ht02.csv",
    }


@pytest.fixture(autouse=True)
def fake_web(monkeypatch: pytest.MonkeyPatch, recorded: dict[str, Path]) -> Iterator[None]:
    """Serve recorded responses instead of the network, and fail the test on any URL that wasn't recorded."""
    unrecognised: list[str] = []

    def fetch(url: str) -> bytes:
        if url not in recorded:
            unrecognised.append(url)
            pytest.fail(f"no recorded response for {url}")
        return recorded[url].read_bytes()

    monkeypatch.setattr(web, "fetch", fetch)
    yield
    # Checked again here in case the code under test swallowed the failure.
    assert not unrecognised, f"no recorded responses for {unrecognised}"
