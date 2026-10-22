"""The price indexes behind the Inflation hurdle: ČSÚ's national CPI and Eurostat's HICP for Czechia."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inflation_station.price_indexes import csu, eurostat
from inflation_station.price_indexes.index_level import CSU_CPI, EUROSTAT_HICP, NAMES, IndexLevel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ["CSU_CPI", "EUROSTAT_HICP", "NAMES", "IndexLevel", "PriceIndex", "price_indexes"]


@dataclass(frozen=True)
class PriceIndex:
    """One price index series: its name, and how to download all its levels."""

    name: str
    fetch: Callable[[], list[IndexLevel]]


def price_indexes(stored: Iterable[IndexLevel]) -> dict[str, PriceIndex]:
    """Each series by its key, fetching levels that continue `stored` (the levels already stored, of any series)."""
    stored = list(stored)
    return {
        CSU_CPI: PriceIndex(NAMES[CSU_CPI], lambda: csu.continuing(csu.cpi(), stored)),
        EUROSTAT_HICP: PriceIndex(NAMES[EUROSTAT_HICP], eurostat.hicp),
    }
