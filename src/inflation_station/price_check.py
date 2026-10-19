"""Compares each buy's or sell's price from the export with the stored price on its date, to catch bad data."""

from decimal import Decimal
from typing import TYPE_CHECKING, NamedTuple

from inflation_station.ledger import BUY, SELL

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import date

    from inflation_station.fund_price import FundPrice
    from inflation_station.ledger import LedgerEntry
    from inflation_station.price_sources import PriceSource
    from inflation_station.purchase import Purchase

# The largest difference from the stored price, as a fraction of it, that passes without a warning: 0.5 %.
# A spot check found the export within 0.005 % of Conseq, so anything above this is worth a look.
MAX_DIFFERENCE = Decimal("0.005")


class _BuyOrSell(NamedTuple):
    day: date
    isin: str
    kind: str  # BUY or SELL
    unit_price: Decimal
    currency: str


def price_warnings(
    purchases: Iterable[Purchase],
    ledger: Iterable[LedgerEntry],
    prices: Iterable[FundPrice],
    *,
    fund_names: Mapping[str, str],
    sources: Mapping[str, PriceSource],
) -> list[str]:
    """A warning for each Purchase, or Managed Portfolio buy or sell, whose price is in another currency than, or
    differs by more than MAX_DIFFERENCE from, the stored price on its date. `fund_names` and `sources` must cover every
    fund bought or sold."""
    by_day = {(p.isin, p.day): p for p in prices}
    buys_and_sells = [_BuyOrSell(p.trade_date, p.isin, BUY, p.unit_price, p.unit_price_currency) for p in purchases]
    buys_and_sells += [
        _BuyOrSell(e.day, e.isin, e.kind, e.unit_price, e.currency)
        for e in ledger
        if e.kind in {BUY, SELL} and e.unit_price is not None
    ]
    warnings = []
    for day, isin, kind, unit_price, currency in sorted(buys_and_sells, key=lambda b: (b.day, b.isin)):
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
        done = "bought" if kind == BUY else "sold"
        warnings.append(
            f"{fund_names[isin]} ({isin}) {done} on {day} at {unit_price} {currency} in the export, "
            f"but {sources[isin].name}'s price that day is {stored.price} {stored.currency} ({problem})."
        )
    return warnings
