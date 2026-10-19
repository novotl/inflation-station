"""Compares each buy's or sell's price from the export with the stored price on its date, to catch bad data."""

from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import date

    from inflation_station.domain import Rows
    from inflation_station.fund_price import FundPrice
    from inflation_station.price_sources import PriceSource

# The largest difference from the stored price, as a fraction of it, that passes without a warning: 0.5 %.
# A spot check found the export within 0.005 % of Conseq, so anything above this is worth a look.
MAX_DIFFERENCE = Decimal("0.005")


class _PurchaseOrSale(NamedTuple):
    day: date
    isin: str
    done: str  # "bought" or "sold"
    unit_price: Decimal
    currency: str


def price_warnings(
    rows: Rows,
    prices: Iterable[FundPrice],
    *,
    fund_names: Mapping[str, str],
    sources: Mapping[str, PriceSource],
) -> list[str]:
    """A warning for each Purchase or Sale whose price is in another currency than, or differs by more than
    MAX_DIFFERENCE from, the stored price on its date. `fund_names` and `sources` must cover every fund bought or sold.
    """
    by_day = {(p.isin, p.day): p for p in prices}
    bought_or_sold = [_PurchaseOrSale(p.day, p.fund.isin, "bought", p.unit_price, p.currency) for p in rows.purchases]
    bought_or_sold += [_PurchaseOrSale(s.day, s.fund.isin, "sold", s.unit_price, s.currency) for s in rows.sales]
    warnings = []
    for day, isin, done, unit_price, currency in sorted(bought_or_sold, key=lambda t: (t.day, t.isin)):
        stored = by_day.get((isin, day))
        if stored is None:
            continue
        if currency != stored.currency:
            problem = "a different currency"
        elif stored.price == 0:  # nothing to measure a difference against
            continue
        else:
            difference = abs(unit_price - stored.price) / stored.price
            if difference <= MAX_DIFFERENCE:
                continue
            problem = f"{difference * 100:.2f} % off"
        warnings.append(
            f"{fund_names[isin]} ({isin}) {done} on {day} at {unit_price} {currency} in the export, "
            f"but {sources[isin].name}'s price that day is {stored.price} {stored.currency} ({problem})."
        )
    return warnings
