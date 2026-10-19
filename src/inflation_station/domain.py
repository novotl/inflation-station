"""The rows every Platform's export is translated into, and what they are in. See CONTEXT.md for each term."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date
    from decimal import Decimal


class Platform(StrEnum):
    """A company you invest through. Its value is its code in the database."""

    JT = "jt"
    INVESTIKA = "investika"
    PORTU = "portu"


@dataclass(frozen=True)
class Portfolio:
    """One pot of money on one Platform. (platform, key) identifies it; the importer picks both, and its name."""

    platform: Platform
    key: str
    name: str


@dataclass(frozen=True)
class Fund:
    """A fund, identified by its ISIN. Its name is the one in the latest import."""

    isin: str
    name: str


# Every imported row: (portfolio, source_row_id) identifies its source row, so re-imports never duplicate it.
# Amounts are never negative: which way the money goes is in what the row is.


@dataclass(frozen=True)
class Deposit:
    """Money moved into the Portfolio's Cash."""

    portfolio: Portfolio
    source_row_id: str
    day: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Purchase:
    """A buy of a Fund's units, paid from Cash in the currency the units are priced in."""

    portfolio: Portfolio
    fund: Fund
    source_row_id: str
    day: date
    units: Decimal
    unit_price: Decimal
    currency: str
    # The Cash spent, without any Fee. Platforms round units, unit_price and amount, so none follows from the others.
    amount: Decimal


@dataclass(frozen=True)
class Sale:
    """A sell of a Fund's units, paid into Cash in the currency the units are priced in."""

    portfolio: Portfolio
    fund: Fund
    source_row_id: str
    day: date
    units: Decimal
    unit_price: Decimal
    currency: str
    # The Cash received, without any Fee.
    amount: Decimal


@dataclass(frozen=True)
class Fee:
    """Money a Platform charged you, paid from Cash."""

    portfolio: Portfolio
    source_row_id: str
    day: date
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class Conversion:
    """Cash changed from one currency to another."""

    portfolio: Portfolio
    source_row_id: str
    day: date
    from_amount: Decimal
    from_currency: str
    to_amount: Decimal
    to_currency: str


# The source_row_id of the Conversion that paid for a Purchase in its currency, when the Platform converts the payment
# itself (J&T Banka): its Purchase's, with this after it.
CONVERSION_SUFFIX = ":conversion"


@dataclass(frozen=True)
class Rows:
    """Imported rows of every kind, from any number of Platforms."""

    deposits: list[Deposit] = field(default_factory=list)
    purchases: list[Purchase] = field(default_factory=list)
    sales: list[Sale] = field(default_factory=list)
    fees: list[Fee] = field(default_factory=list)
    conversions: list[Conversion] = field(default_factory=list)

    def __add__(self, other: Rows) -> Rows:
        return Rows(
            deposits=self.deposits + other.deposits,
            purchases=self.purchases + other.purchases,
            sales=self.sales + other.sales,
            fees=self.fees + other.fees,
            conversions=self.conversions + other.conversions,
        )

    def __bool__(self) -> bool:
        return any((self.deposits, self.purchases, self.sales, self.fees, self.conversions))

    def funds(self) -> dict[str, Fund]:
        """Every Fund bought or sold, by ISIN, sorted by ISIN, named as in its latest Purchase or Sale."""
        trades = sorted([*self.purchases, *self.sales], key=lambda t: t.day)
        return dict(sorted({t.fund.isin: t.fund for t in trades}.items()))

    def first_days(self) -> dict[str, date]:
        """The day of the first row in each currency, by currency, sorted by currency."""
        return first_days(
            [(d.day, d.currency) for d in self.deposits]
            + [(t.day, t.currency) for t in [*self.purchases, *self.sales]]
            + [(f.day, f.currency) for f in self.fees]
            + [(c.day, cur) for c in self.conversions for cur in (c.from_currency, c.to_currency)]
        )


def first_days(dated: Iterable[tuple[date, str]]) -> dict[str, date]:
    """The first day of each currency in (day, currency) pairs, by currency, sorted by currency."""
    first: dict[str, date] = {}
    for day, currency in sorted(dated):
        first.setdefault(currency, day)
    return dict(sorted(first.items()))
