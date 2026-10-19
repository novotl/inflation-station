from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, override

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Dialect, Engine, String, UniqueConstraint, create_engine, select, tuple_
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from inflation_station.fee import Fee
from inflation_station.fund_price import FundPrice
from inflation_station.fx_rate import FxRate
from inflation_station.ledger import LedgerEntry
from inflation_station.price_index import IndexLevel
from inflation_station.purchase import Purchase

if TYPE_CHECKING:
    from collections.abc import Iterable


DATABASE_NAME = "inflation-station.sqlite"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DecimalText(TypeDecorator[Decimal]):
    """A Decimal stored as text, so amounts never pass through a float."""

    impl = String
    cache_ok = True

    @override
    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    @override
    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class UTCDateTime(TypeDecorator[datetime]):
    """An aware datetime stored as a naive UTC timestamp. Naive datetimes are rejected."""

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            msg = f"refusing to store naive datetime {value}"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this class attribute
        Decimal: DecimalText,
        datetime: UTCDateTime,
    }


class PurchaseRecord(Base):
    __tablename__ = "purchase"
    __table_args__ = (UniqueConstraint("platform", "portfolio_id", "source_row_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    portfolio_id: Mapped[str]
    source_row_id: Mapped[str]
    isin: Mapped[str]
    fund_name: Mapped[str]
    trade_date: Mapped[date]
    units: Mapped[Decimal]
    unit_price: Mapped[Decimal]
    unit_price_currency: Mapped[str]
    czk: Mapped[Decimal]
    imported_at: Mapped[datetime]


class LedgerEntryRecord(Base):
    __tablename__ = "ledger_entry"
    __table_args__ = (UniqueConstraint("platform", "portfolio_id", "source_row_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    portfolio_id: Mapped[str]
    source_row_id: Mapped[str]
    day: Mapped[date]
    kind: Mapped[str]
    isin: Mapped[str]
    fund_name: Mapped[str]
    units: Mapped[Decimal]
    unit_price: Mapped[Decimal | None]
    amount: Mapped[Decimal]
    currency: Mapped[str]
    imported_at: Mapped[datetime]


class FeeRecord(Base):
    __tablename__ = "fee"
    __table_args__ = (UniqueConstraint("platform", "portfolio_id", "source_row_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    portfolio_id: Mapped[str]
    source_row_id: Mapped[str]
    day: Mapped[date]
    isin: Mapped[str]
    czk: Mapped[Decimal]
    imported_at: Mapped[datetime]


class FundPriceRecord(Base):
    __tablename__ = "fund_price"
    __table_args__ = (UniqueConstraint("isin", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str]
    day: Mapped[date]
    price: Mapped[Decimal]
    currency: Mapped[str]


class FxRateRecord(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("currency", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str]
    day: Mapped[date]
    czk_per_unit: Mapped[Decimal]


class PriceIndexRecord(Base):
    __tablename__ = "price_index"
    __table_args__ = (UniqueConstraint("series", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series: Mapped[str]
    month: Mapped[date]
    level: Mapped[Decimal]


@dataclass(frozen=True)
class Added:
    added: int
    already_present: int


def database_exists(data_dir: Path) -> bool:
    return (data_dir / DATABASE_NAME).exists()


def database_url(data_dir: Path) -> str:
    return f"sqlite:///{data_dir / DATABASE_NAME}"


def engine(url: str) -> Engine:
    # A short-lived CLI gains nothing from pooling; NullPool closes each connection when it's released.
    return create_engine(url, poolclass=NullPool)


def migrate(url: str, revision: str = "head") -> None:
    """Bring the database at `url` up to `revision`, by default the latest schema."""
    config = Config(attributes={"url": url})
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, revision)


class Store:
    """The SQLite database in the data directory. The only place that talks to the database.

    Amounts are stored as decimal text, never as floats; timestamps as UTC.
    """

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        url = database_url(data_dir)
        migrate(url)
        self._engine = engine(url)

    def add_purchases(self, purchases: Iterable[Purchase]) -> Added:
        imported_at = datetime.now(UTC)
        purchases = list(purchases)
        key_columns = (PurchaseRecord.platform, PurchaseRecord.portfolio_id, PurchaseRecord.source_row_id)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(select(*key_columns).where(tuple_(*key_columns).in_([_key(p) for p in purchases])))
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for purchase in purchases:
                if _key(purchase) in seen:
                    already_present += 1
                    continue
                seen.add(_key(purchase))
                session.add(_record(purchase, imported_at))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_ledger_entries(self, entries: Iterable[LedgerEntry]) -> Added:
        imported_at = datetime.now(UTC)
        entries = list(entries)
        key_columns = (LedgerEntryRecord.platform, LedgerEntryRecord.portfolio_id, LedgerEntryRecord.source_row_id)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(select(*key_columns).where(tuple_(*key_columns).in_([_key(e) for e in entries])))
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for entry in entries:
                if _key(entry) in seen:
                    already_present += 1
                    continue
                seen.add(_key(entry))
                session.add(_ledger_record(entry, imported_at))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_fees(self, fees: Iterable[Fee]) -> Added:
        imported_at = datetime.now(UTC)
        fees = list(fees)
        key_columns = (FeeRecord.platform, FeeRecord.portfolio_id, FeeRecord.source_row_id)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(select(*key_columns).where(tuple_(*key_columns).in_([_key(f) for f in fees])))
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for fee in fees:
                if _key(fee) in seen:
                    already_present += 1
                    continue
                seen.add(_key(fee))
                session.add(_fee_record(fee, imported_at))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_fund_prices(self, prices: Iterable[FundPrice]) -> Added:
        """Adds the prices not stored yet. A stored price is kept, even if `prices` has a different one that day."""
        prices = list(prices)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(
                select(FundPriceRecord.isin, FundPriceRecord.day).where(
                    FundPriceRecord.isin.in_({p.isin for p in prices})
                )
            )
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for price in prices:
                if (price.isin, price.day) in seen:
                    already_present += 1
                    continue
                seen.add((price.isin, price.day))
                session.add(FundPriceRecord(isin=price.isin, day=price.day, price=price.price, currency=price.currency))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_fx_rates(self, rates: Iterable[FxRate]) -> Added:
        """Adds the rates not stored yet. A stored rate is kept, even if `rates` has a different one that day."""
        rates = list(rates)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(
                select(FxRateRecord.currency, FxRateRecord.day).where(
                    FxRateRecord.currency.in_({r.currency for r in rates})
                )
            )
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for rate in rates:
                if (rate.currency, rate.day) in seen:
                    already_present += 1
                    continue
                seen.add((rate.currency, rate.day))
                session.add(FxRateRecord(currency=rate.currency, day=rate.day, czk_per_unit=rate.czk_per_unit))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_index_levels(self, levels: Iterable[IndexLevel]) -> Added:
        """Adds the levels not stored yet. A stored level is kept, even if `levels` has a different one that month."""
        levels = list(levels)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(
                select(PriceIndexRecord.series, PriceIndexRecord.month).where(
                    PriceIndexRecord.series.in_({i.series for i in levels})
                )
            )
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for level in levels:
                if (level.series, level.month) in seen:
                    already_present += 1
                    continue
                seen.add((level.series, level.month))
                session.add(PriceIndexRecord(series=level.series, month=level.month, level=level.level))
                added += 1
        return Added(added=added, already_present=already_present)

    def purchases(self) -> list[Purchase]:
        with Session(self._engine) as session:
            return [_purchase(record) for record in session.scalars(select(PurchaseRecord))]

    def ledger(self) -> list[LedgerEntry]:
        with Session(self._engine) as session:
            return [_ledger_entry(record) for record in session.scalars(select(LedgerEntryRecord))]

    def fees(self) -> list[Fee]:
        with Session(self._engine) as session:
            return [_fee(record) for record in session.scalars(select(FeeRecord))]

    def fund_prices(self) -> list[FundPrice]:
        with Session(self._engine) as session:
            return [
                FundPrice(isin=r.isin, day=r.day, price=r.price, currency=r.currency)
                for r in session.scalars(select(FundPriceRecord))
            ]

    def fx_rates(self) -> list[FxRate]:
        with Session(self._engine) as session:
            return [
                FxRate(currency=r.currency, day=r.day, czk_per_unit=r.czk_per_unit)
                for r in session.scalars(select(FxRateRecord))
            ]

    def index_levels(self) -> list[IndexLevel]:
        with Session(self._engine) as session:
            return [
                IndexLevel(series=r.series, month=r.month, level=r.level)
                for r in session.scalars(select(PriceIndexRecord))
            ]


def _key(row: Purchase | Fee | LedgerEntry) -> tuple[str, str, str]:
    """What identifies an imported row."""
    return (row.platform, row.portfolio_id, row.source_row_id)


def _record(p: Purchase, imported_at: datetime) -> PurchaseRecord:
    return PurchaseRecord(
        platform=p.platform,
        portfolio_id=p.portfolio_id,
        source_row_id=p.source_row_id,
        isin=p.isin,
        fund_name=p.fund_name,
        trade_date=p.trade_date,
        units=p.units,
        unit_price=p.unit_price,
        unit_price_currency=p.unit_price_currency,
        czk=p.czk,
        imported_at=imported_at,
    )


def _purchase(r: PurchaseRecord) -> Purchase:
    return Purchase(**{f.name: getattr(r, f.name) for f in fields(Purchase)})


def _ledger_record(e: LedgerEntry, imported_at: datetime) -> LedgerEntryRecord:
    return LedgerEntryRecord(**{f.name: getattr(e, f.name) for f in fields(LedgerEntry)}, imported_at=imported_at)


def _ledger_entry(r: LedgerEntryRecord) -> LedgerEntry:
    return LedgerEntry(**{f.name: getattr(r, f.name) for f in fields(LedgerEntry)})


def _fee_record(fee: Fee, imported_at: datetime) -> FeeRecord:
    return FeeRecord(**{f.name: getattr(fee, f.name) for f in fields(Fee)}, imported_at=imported_at)


def _fee(r: FeeRecord) -> Fee:
    return Fee(**{f.name: getattr(r, f.name) for f in fields(Fee)})
