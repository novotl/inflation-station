from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True)
class FxRate:
    """What one unit of `currency` cost in CZK on one day, as ČNB published it. (currency, day) identifies it."""

    currency: str
    day: date
    czk_per_unit: Decimal
