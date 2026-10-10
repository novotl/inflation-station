from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

# ČSÚ's national CPI, the headline "míra inflace".
CSU_CPI = "csu_cpi"


@dataclass(frozen=True)
class IndexLevel:
    """A price index's level in one month. (series, month) identifies it; `month` is the month's first day.

    Only ratios between levels of one series mean anything: each series has its own base.
    """

    series: str
    month: date
    level: Decimal
