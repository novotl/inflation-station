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

from inflation_station.fund_price import FundPrice
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
    __table_args__ = (UniqueConstraint("platform", "account_id", "source_row_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]
    account_id: Mapped[str]
    source_row_id: Mapped[str]
    isin: Mapped[str]
    fund_name: Mapped[str]
    trade_date: Mapped[date]
    units: Mapped[Decimal]
    unit_price: Mapped[Decimal]
    unit_price_currency: Mapped[str]
    gross_czk: Mapped[Decimal]
    fee: Mapped[Decimal]
    fee_currency: Mapped[str]
    imported_at: Mapped[datetime]


class FundPriceRecord(Base):
    __tablename__ = "fund_price"
    __table_args__ = (UniqueConstraint("isin", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str]
    day: Mapped[date]
    price: Mapped[Decimal]
    currency: Mapped[str]


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


def migrate(url: str) -> None:
    """Bring the database at `url` up to the latest schema."""
    config = Config(attributes={"url": url})
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(config, "head")


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
        key_columns = (PurchaseRecord.platform, PurchaseRecord.account_id, PurchaseRecord.source_row_id)
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

    def purchases(self) -> list[Purchase]:
        with Session(self._engine) as session:
            return [_purchase(record) for record in session.scalars(select(PurchaseRecord))]

    def fund_prices(self) -> list[FundPrice]:
        with Session(self._engine) as session:
            return [
                FundPrice(isin=r.isin, day=r.day, price=r.price, currency=r.currency)
                for r in session.scalars(select(FundPriceRecord))
            ]


def _key(p: Purchase) -> tuple[str, str, str]:
    return (p.platform, p.account_id, p.source_row_id)


def _record(p: Purchase, imported_at: datetime) -> PurchaseRecord:
    return PurchaseRecord(
        platform=p.platform,
        account_id=p.account_id,
        source_row_id=p.source_row_id,
        isin=p.isin,
        fund_name=p.fund_name,
        trade_date=p.trade_date,
        units=p.units,
        unit_price=p.unit_price,
        unit_price_currency=p.unit_price_currency,
        gross_czk=p.gross_czk,
        fee=p.fee,
        fee_currency=p.fee_currency,
        imported_at=imported_at,
    )


def _purchase(r: PurchaseRecord) -> Purchase:
    return Purchase(**{f.name: getattr(r, f.name) for f in fields(Purchase)})
