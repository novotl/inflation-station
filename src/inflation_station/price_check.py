"""Compares each Purchase's price from the export with the stored price on its trade date, to catch bad data."""

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from inflation_station.fund_price import FundPrice
    from inflation_station.purchase import Purchase

# The largest difference from the stored price, as a fraction of it, that passes without a warning: 0.5 %.
# A spot check found the export within 0.005 % of Conseq, so anything above this is worth a look.
MAX_DIFFERENCE = Decimal("0.005")


def price_warnings(purchases: Iterable[Purchase], prices: Iterable[FundPrice]) -> list[str]:
    """A warning for each Purchase whose price is in another currency than, or differs by more than MAX_DIFFERENCE
    from, the stored price on its trade date."""
    by_day = {(p.isin, p.day): p for p in prices}
    warnings = []
    for purchase in sorted(purchases, key=lambda p: (p.trade_date, p.isin)):
        conseq = by_day.get((purchase.isin, purchase.trade_date))
        if conseq is None:
            continue
        if purchase.unit_price_currency != conseq.currency:
            problem = "a different currency"
        elif conseq.price == 0:  # nothing to measure a difference against
            continue
        else:
            difference = abs(purchase.unit_price - conseq.price) / conseq.price
            if difference <= MAX_DIFFERENCE:
                continue
            problem = f"{difference * 100:.2f} % off"
        warnings.append(
            f"{purchase.fund_name} ({purchase.isin}) bought on {purchase.trade_date} at {purchase.unit_price} "
            f"{purchase.unit_price_currency} in the export, but Conseq's price that day is {conseq.price} "
            f"{conseq.currency} ({problem})."
        )
    return warnings
