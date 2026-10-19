from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from inflation_station.purchase import Purchase


@dataclass(frozen=True)
class Fee:
    """CZK a Platform charged you on a Purchase, outside a Managed Portfolio. It is money invested, never Value.

    (platform, portfolio_id, source_row_id) is the source row of the Purchase it was charged on, so re-imports never
    duplicate it and it can always be found next to its Purchase.
    """

    platform: str
    portfolio_id: str
    source_row_id: str
    day: date
    # The Holding it was charged on, by ISIN.
    isin: str
    czk: Decimal


def charged_on(purchase: Purchase, czk: Decimal) -> list[Fee]:
    """The Fee of `czk` charged on a Purchase, or none if `czk` is zero."""
    if not czk:
        return []
    return [
        Fee(
            platform=purchase.platform,
            portfolio_id=purchase.portfolio_id,
            source_row_id=purchase.source_row_id,
            day=purchase.trade_date,
            isin=purchase.isin,
            czk=czk,
        )
    ]
