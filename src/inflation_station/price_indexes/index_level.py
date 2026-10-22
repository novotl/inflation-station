from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

# ČSÚ's national CPI, the headline "míra inflace".
CSU_CPI = "csu_cpi"
# Eurostat's HICP for Czechia, harmonised across the EU.
EUROSTAT_HICP = "eurostat_hicp"
# The name each series goes by, in messages and the chart's legend.
NAMES = {CSU_CPI: "ČSÚ CPI", EUROSTAT_HICP: "Eurostat HICP"}


@dataclass(frozen=True)
class IndexLevel:
    """A price index's level in one month. (series, month) identifies it; `month` is the month's first day.

    Only ratios between levels of one series mean anything: each series has its own base.
    """

    series: str
    month: date
    level: Decimal
