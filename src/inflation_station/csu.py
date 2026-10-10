"""Downloads ČSÚ's (the Czech Statistical Office's) national CPI and chains its month-on-month changes into levels.

The index-level datasets are avoided: they break at the January 2026 switch to COICOP 2018. The month-on-month
changes run on across it.
"""

import csv
import io
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station import web
from inflation_station.errors import InflationStationError
from inflation_station.price_index import CSU_CPI, IndexLevel

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

URL = "https://data.csu.gov.cz/api/dotaz/v1/data/vybery/CEN0101HT02?format=CSV"
# The selection also has year-on-year changes and the 12-month average; only month-on-month rows are chained.
MONTH_ON_MONTH = "k předchozímu měsíci"
MONTHS = (
    "leden",
    "únor",
    "březen",
    "duben",
    "květen",
    "červen",
    "červenec",
    "srpen",
    "září",
    "říjen",
    "listopad",
    "prosinec",
)
# The level of the month before the first change, which the others are chained from.
BASE = Decimal(100)


def cpi() -> list[IndexLevel]:
    """A level for every month ČSÚ published a change for, and for the month before the first of them."""
    try:
        return _chain(_changes(web.fetch(URL)))
    except (csv.Error, ValueError, KeyError, ArithmeticError) as e:
        msg = f"cannot read {URL}: {e}"
        raise InflationStationError(msg) from e


def continuing(levels: Sequence[IndexLevel], stored: Iterable[IndexLevel]) -> list[IndexLevel]:
    """`levels` rescaled to agree with `stored` in the latest month both have, so the series keeps one base.

    Each fetch chains from its own first month; were ČSÚ's selection to start later, the new months would otherwise
    be appended at a different scale. Unchanged when nothing is stored for those months.
    """
    at = {i.month: i.level for i in stored if i.series == CSU_CPI}
    common = [i for i in levels if i.month in at]
    if not common:
        return list(levels)
    anchor = max(common, key=lambda i: i.month)
    scale = at[anchor.month] / anchor.level
    return [replace(i, level=i.level * scale) for i in levels]


def _changes(response: bytes) -> dict[date, Decimal]:
    """The month-on-month changes in percent, by month."""
    rows = csv.DictReader(io.StringIO(response.decode("utf-8-sig")))
    changes = {_month(r["Měsíce"]): Decimal(r["Hodnota"]) for r in rows if r["Ukazatel"].endswith(MONTH_ON_MONTH)}
    if not changes:
        msg = "no month-on-month changes"
        raise ValueError(msg)
    return changes


def _chain(changes: dict[date, Decimal]) -> list[IndexLevel]:
    """Levels from BASE in the month before the first change. Raises on a gap, as chaining across one would be wrong."""
    month = (min(changes) - timedelta(days=1)).replace(day=1)
    levels = [IndexLevel(series=CSU_CPI, month=month, level=BASE)]
    while len(levels) <= len(changes):
        month = (month + timedelta(days=31)).replace(day=1)
        if month not in changes:
            msg = f"no month-on-month change for {month:%Y-%m}"
            raise ValueError(msg)
        # A change of 0.3 means this month's prices are 0.3 % above last month's.
        levels.append(IndexLevel(series=CSU_CPI, month=month, level=levels[-1].level * (1 + changes[month] / 100)))
    return levels


def _month(text: str) -> date:
    """The first day of a month written in Czech, e.g. `srpen 2026`."""
    name, _, year = text.partition(" ")
    if name not in MONTHS or not year.isdigit():
        msg = f"unknown month {text!r}"
        raise ValueError(msg)
    return date(int(year), MONTHS.index(name) + 1, 1)
