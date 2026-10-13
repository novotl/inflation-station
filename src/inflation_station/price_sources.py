"""Where each fund's prices come from: Conseq for the funds it sells, Yahoo Finance for exchange-traded ones."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inflation_station import conseq, yahoo
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from inflation_station.fund_price import FundPrice


@dataclass(frozen=True)
class PriceSource:
    """One fund's price source: its name, and how to download all its prices."""

    name: str
    fetch: Callable[[], list[FundPrice]]


def price_sources(funds: Mapping[str, str]) -> dict[str, PriceSource]:
    """The price source of each fund in `funds` (ISIN -> fund name), from the hand-edited mappings.

    Raises naming every fund in neither mapping, and every ISIN in both, purchased or held or not.
    """
    pages, tickers = conseq.fund_pages(), yahoo.tickers()
    in_both = sorted(pages.keys() & tickers.keys())
    if in_both:
        msg = (
            f"{_names(funds, in_both)} is listed in both {conseq.FUND_PAGES} and {yahoo.TICKERS}; "
            "remove it from one of them"
        )
        raise InflationStationError(msg)
    in_neither = [isin for isin in funds if isin not in pages and isin not in tickers]
    if in_neither:
        page_lines = ", ".join(f'{isin} = "<fund page URL>"' for isin in in_neither)
        ticker_lines = ", ".join(f'{isin} = "<ticker>"' for isin in in_neither)
        msg = (
            f"no price source for {_names(funds, in_neither)}. If Conseq has the fund, find it on "
            f"{conseq.FUND_LIST}, check the ISIN on its page, and add the page's URL to {conseq.FUND_PAGES} as: "
            f"{page_lines}. If it is exchange-traded, add the Yahoo Finance ticker of the listing in the currency it "
            f"was bought in to {yahoo.TICKERS} as: {ticker_lines}"
        )
        raise InflationStationError(msg)
    return {isin: _source(isin, pages, tickers) for isin in funds}


def _source(isin: str, pages: Mapping[str, str], tickers: Mapping[str, str]) -> PriceSource:
    if isin in pages:
        return PriceSource("Conseq", lambda: conseq.price_history(isin, pages[isin]))
    return PriceSource("Yahoo Finance", lambda: yahoo.price_history(isin, tickers[isin]))


def _names(funds: Mapping[str, str], isins: list[str]) -> str:
    """Each ISIN with its fund's name, or bare if it was never purchased or held."""
    return ", ".join(f"{funds[isin]} ({isin})" if isin in funds else isin for isin in isins)
