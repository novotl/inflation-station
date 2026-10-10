from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True)
class FundPrice:
    """A fund's price per unit on one day, in the currency the fund is priced in. (isin, day) identifies it."""

    isin: str
    day: date
    price: Decimal
    currency: str
