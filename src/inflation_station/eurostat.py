"""Downloads Eurostat's HICP for Czechia, the EU-harmonised measure of inflation, as index levels.

`prc_hicp_minr` is the ECOICOP 2 dataset; the legacy `prc_hicp_midx` stops in 2025.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from inflation_station import web
from inflation_station.errors import InflationStationError
from inflation_station.price_index import EUROSTAT_HICP, IndexLevel

URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
    "?geo=CZ&coicop18=TOTAL&unit=I15&format=JSON&lang=EN"
)
TIME = "time"


def hicp() -> list[IndexLevel]:
    """A level for every month Eurostat published one for (2015 = 100)."""
    try:
        return _levels(json.loads(web.fetch(URL), parse_float=Decimal))
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as e:
        msg = f"cannot read {URL}: {e}"
        raise InflationStationError(msg) from e


def _levels(dataset: dict[str, Any]) -> list[IndexLevel]:
    """The levels in a JSON-stat 2.0 dataset of one monthly series.

    Values are keyed by their position across all dimensions; with time last and every other dimension a single
    category, that is the month's position. Months without a value, not published yet, are skipped at either end;
    raises on one between published months, as interpolating across it would be wrong.
    """
    dimensions = dict(zip(dataset["id"], dataset["size"], strict=True))
    if list(dimensions)[-1] != TIME or any(size != 1 for d, size in dimensions.items() if d != TIME):
        msg = "not a single monthly series"
        raise ValueError(msg)
    values = dataset["value"]
    levels = [
        IndexLevel(series=EUROSTAT_HICP, month=date.fromisoformat(f"{month}-01"), level=Decimal(values[str(n)]))
        for month, n in dataset["dimension"][TIME]["category"]["index"].items()
        if str(n) in values
    ]
    if not levels:
        msg = "no index levels"
        raise ValueError(msg)
    for before, after in pairwise(levels):
        month = (before.month + timedelta(days=31)).replace(day=1)
        if after.month != month:
            msg = f"no index level for {month:%Y-%m}"
            raise ValueError(msg)
    return levels
