from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@dataclass(frozen=True)
class Purchase:
    """A buy of fund units, independent of the platform it was imported from.

    (platform, account_id, source_row_id) identifies the source row, so re-imports never duplicate it.
    """

    platform: str
    account_id: str
    source_row_id: str
    isin: str
    fund_name: str
    trade_date: date
    units: Decimal
    unit_price: Decimal
    unit_price_currency: str
    gross_czk: Decimal
    fee: Decimal
    fee_currency: str
