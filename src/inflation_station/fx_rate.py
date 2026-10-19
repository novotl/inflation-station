from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True)
class FxRate:
    """`from_amount` of `from_currency` cost `to_amount` of `to_currency` on one day, as the publisher quoted it (ČNB
    quotes some currencies per 100 units). (day, from_currency, to_currency) identifies it.
    """

    day: date
    from_currency: str
    from_amount: Decimal
    to_currency: str
    to_amount: Decimal

    @property
    def rate(self) -> Decimal:
        """What one unit of `from_currency` cost in `to_currency`."""
        return self.to_amount / self.from_amount
