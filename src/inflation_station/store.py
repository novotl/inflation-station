from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, override

from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Dialect,
    Engine,
    ForeignKey,
    String,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from inflation_station.domain import Conversion, Deposit, Fee, Fund, Platform, Portfolio, Purchase, Rows, Sale
from inflation_station.errors import InflationStationError
from inflation_station.fx_rate import FxRate
from inflation_station.price_indexes import IndexLevel
from inflation_station.price_sources import FundPrice

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


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


class PlatformRecord(Base):
    __tablename__ = "platform"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)


class PortfolioRecord(Base):
    __tablename__ = "portfolio"
    __table_args__ = (UniqueConstraint("platform_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id"))
    key: Mapped[str]
    name: Mapped[str]


class FundRecord(Base):
    __tablename__ = "fund"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]


def _currency_check(column: str) -> CheckConstraint:
    """Three capital letters; which codes are currencies the code checks (currency.py)."""
    return CheckConstraint(f"{column} GLOB '[A-Z][A-Z][A-Z]'", name=f"{column}_is_three_capitals")


def _imported_row_args(*currency_columns: str) -> tuple[UniqueConstraint | CheckConstraint, ...]:
    return (UniqueConstraint("portfolio_id", "source_row_id"), *map(_currency_check, currency_columns))


class _ImportedRow(Base):
    """The columns of every imported row: its Portfolio, and its source row there, which identifies it."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"))
    source_row_id: Mapped[str]
    day: Mapped[date]
    imported_at: Mapped[datetime]


class DepositRecord(_ImportedRow):
    __tablename__ = "deposit"
    __table_args__ = _imported_row_args("currency")

    amount: Mapped[Decimal]
    currency: Mapped[str]


class _PurchaseOrSaleRow(_ImportedRow):
    __abstract__ = True

    fund_id: Mapped[int] = mapped_column(ForeignKey("fund.id"))
    units: Mapped[Decimal]
    unit_price: Mapped[Decimal]
    amount: Mapped[Decimal]
    currency: Mapped[str]


class PurchaseRecord(_PurchaseOrSaleRow):
    __tablename__ = "purchase"
    __table_args__ = _imported_row_args("currency")


class SaleRecord(_PurchaseOrSaleRow):
    __tablename__ = "sale"
    __table_args__ = _imported_row_args("currency")


class FeeRecord(_ImportedRow):
    __tablename__ = "fee"
    __table_args__ = _imported_row_args("currency")

    amount: Mapped[Decimal]
    currency: Mapped[str]


class ConversionRecord(_ImportedRow):
    __tablename__ = "conversion"
    __table_args__ = _imported_row_args("from_currency", "to_currency")

    from_amount: Mapped[Decimal]
    from_currency: Mapped[str]
    to_amount: Mapped[Decimal]
    to_currency: Mapped[str]


class FundPriceRecord(Base):
    __tablename__ = "fund_price"
    __table_args__ = (UniqueConstraint("fund_id", "day"), _currency_check("currency"))

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund.id"))
    day: Mapped[date]
    price: Mapped[Decimal]
    currency: Mapped[str]


class FxRateRecord(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (
        UniqueConstraint("day", "from_currency", "to_currency"),
        _currency_check("from_currency"),
        _currency_check("to_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date]
    from_amount: Mapped[Decimal]
    from_currency: Mapped[str]
    to_amount: Mapped[Decimal]
    to_currency: Mapped[str]


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
    created = create_engine(url, poolclass=NullPool)
    # SQLite checks foreign keys only when asked to, connection by connection.
    event.listen(created, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys = ON"))
    return created


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
        try:
            migrate(url)
        except CommandError as e:
            # Migrations before the normalized schema were squashed into it, so there is nothing to upgrade from.
            msg = (
                f"{data_dir / DATABASE_NAME} was stored by an older version that can't be upgraded ({e}); delete it, "
                "import your exports again and fetch prices, rates and price indices again"
            )
            raise InflationStationError(msg) from e
        self._engine = engine(url)

    def add_rows(self, rows: Rows) -> dict[str, Added]:
        """Adds the rows not stored yet, with their Portfolios and Funds, by kind (e.g. "Purchases").

        A stored row is kept, even if `rows` has a different one with its identity. A Portfolio's and a Fund's name is
        the one in `rows`, if it has them: the latest import wins.
        """
        imported_at = datetime.now(UTC)
        with Session(self._engine) as session, session.begin():
            portfolio_ids = _store_portfolios(session, rows)
            fund_ids = _store_funds(session, rows)

            def add[R](records: type[_ImportedRow], kind: list[R], record: Callable[[R], _ImportedRow]) -> Added:
                ids = set(portfolio_ids.values())
                stored = session.execute(
                    select(records.portfolio_id, records.source_row_id).where(records.portfolio_id.in_(ids))
                )
                seen = {tuple(row) for row in stored}
                added = already_present = 0
                for row in kind:
                    new = record(row)
                    new.imported_at = imported_at
                    if (new.portfolio_id, new.source_row_id) in seen:
                        already_present += 1
                        continue
                    seen.add((new.portfolio_id, new.source_row_id))
                    session.add(new)
                    added += 1
                return Added(added=added, already_present=already_present)

            def purchase_or_sale(record: type[_PurchaseOrSaleRow]) -> Callable[[Purchase | Sale], _PurchaseOrSaleRow]:
                return lambda t: record(
                    portfolio_id=portfolio_ids[_portfolio_key(t.portfolio)],
                    fund_id=fund_ids[t.fund.isin],
                    source_row_id=t.source_row_id,
                    day=t.day,
                    units=t.units,
                    unit_price=t.unit_price,
                    amount=t.amount,
                    currency=t.currency,
                )

            return {
                "Deposits": add(
                    DepositRecord,
                    rows.deposits,
                    lambda d: DepositRecord(
                        portfolio_id=portfolio_ids[_portfolio_key(d.portfolio)],
                        source_row_id=d.source_row_id,
                        day=d.day,
                        amount=d.amount,
                        currency=d.currency,
                    ),
                ),
                "Purchases": add(PurchaseRecord, rows.purchases, purchase_or_sale(PurchaseRecord)),
                "Sales": add(SaleRecord, rows.sales, purchase_or_sale(SaleRecord)),
                "Fees": add(
                    FeeRecord,
                    rows.fees,
                    lambda f: FeeRecord(
                        portfolio_id=portfolio_ids[_portfolio_key(f.portfolio)],
                        source_row_id=f.source_row_id,
                        day=f.day,
                        amount=f.amount,
                        currency=f.currency,
                    ),
                ),
                "Conversions": add(
                    ConversionRecord,
                    rows.conversions,
                    lambda c: ConversionRecord(
                        portfolio_id=portfolio_ids[_portfolio_key(c.portfolio)],
                        source_row_id=c.source_row_id,
                        day=c.day,
                        from_amount=c.from_amount,
                        from_currency=c.from_currency,
                        to_amount=c.to_amount,
                        to_currency=c.to_currency,
                    ),
                ),
            }

    def add_fund_prices(self, prices: Iterable[FundPrice]) -> Added:
        """Adds the prices not stored yet. A stored price is kept, even if `prices` has a different one that day.

        Every price must be of a stored Fund.
        """
        prices = list(prices)
        with Session(self._engine) as session, session.begin():
            fund_ids = dict(
                session.execute(
                    select(FundRecord.isin, FundRecord.id).where(FundRecord.isin.in_({p.isin for p in prices}))
                ).all()
            )
            unknown = sorted({p.isin for p in prices} - fund_ids.keys())
            if unknown:
                msg = f"prices of funds never bought or sold: {', '.join(unknown)}"
                raise ValueError(msg)
            stored = session.execute(
                select(FundPriceRecord.fund_id, FundPriceRecord.day).where(
                    FundPriceRecord.fund_id.in_(fund_ids.values())
                )
            )
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for price in prices:
                key = (fund_ids[price.isin], price.day)
                if key in seen:
                    already_present += 1
                    continue
                seen.add(key)
                session.add(FundPriceRecord(fund_id=key[0], day=price.day, price=price.price, currency=price.currency))
                added += 1
        return Added(added=added, already_present=already_present)

    def add_fx_rates(self, rates: Iterable[FxRate]) -> Added:
        """Adds the rates not stored yet. A stored rate is kept, even if `rates` has a different one that day."""
        rates = list(rates)
        with Session(self._engine) as session, session.begin():
            stored = session.execute(
                select(FxRateRecord.day, FxRateRecord.from_currency, FxRateRecord.to_currency).where(
                    FxRateRecord.from_currency.in_({r.from_currency for r in rates})
                )
            )
            seen = {tuple(row) for row in stored}
            added = already_present = 0
            for rate in rates:
                key = (rate.day, rate.from_currency, rate.to_currency)
                if key in seen:
                    already_present += 1
                    continue
                seen.add(key)
                session.add(FxRateRecord(**{f.name: getattr(rate, f.name) for f in fields(FxRate)}))
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

    def rows(self) -> Rows:
        """Every stored row, each kind in the order stored."""
        with Session(self._engine) as session:
            platforms = dict(session.execute(select(PlatformRecord.id, PlatformRecord.code)).all())
            portfolios = {
                r.id: Portfolio(Platform(platforms[r.platform_id]), r.key, r.name)
                for r in session.scalars(select(PortfolioRecord))
            }
            funds = {r.id: Fund(r.isin, r.name) for r in session.scalars(select(FundRecord))}

            def purchases_or_sales[T: (Purchase, Sale)](record: type[_PurchaseOrSaleRow], kind: type[T]) -> list[T]:
                return [
                    kind(
                        portfolio=portfolios[r.portfolio_id],
                        fund=funds[r.fund_id],
                        source_row_id=r.source_row_id,
                        day=r.day,
                        units=r.units,
                        unit_price=r.unit_price,
                        currency=r.currency,
                        amount=r.amount,
                    )
                    for r in session.scalars(select(record).order_by(record.id))
                ]

            return Rows(
                deposits=[
                    Deposit(portfolios[r.portfolio_id], r.source_row_id, r.day, r.amount, r.currency)
                    for r in session.scalars(select(DepositRecord).order_by(DepositRecord.id))
                ],
                purchases=purchases_or_sales(PurchaseRecord, Purchase),
                sales=purchases_or_sales(SaleRecord, Sale),
                fees=[
                    Fee(portfolios[r.portfolio_id], r.source_row_id, r.day, r.amount, r.currency)
                    for r in session.scalars(select(FeeRecord).order_by(FeeRecord.id))
                ],
                conversions=[
                    Conversion(
                        portfolio=portfolios[r.portfolio_id],
                        source_row_id=r.source_row_id,
                        day=r.day,
                        from_amount=r.from_amount,
                        from_currency=r.from_currency,
                        to_amount=r.to_amount,
                        to_currency=r.to_currency,
                    )
                    for r in session.scalars(select(ConversionRecord).order_by(ConversionRecord.id))
                ],
            )

    def fund_prices(self) -> list[FundPrice]:
        with Session(self._engine) as session:
            return [
                FundPrice(isin=isin, day=r.day, price=r.price, currency=r.currency)
                for r, isin in session.execute(
                    select(FundPriceRecord, FundRecord.isin).join(FundRecord).order_by(FundPriceRecord.id)
                )
            ]

    def fx_rates(self) -> list[FxRate]:
        with Session(self._engine) as session:
            return [
                FxRate(**{f.name: getattr(r, f.name) for f in fields(FxRate)})
                for r in session.scalars(select(FxRateRecord).order_by(FxRateRecord.id))
            ]

    def index_levels(self) -> list[IndexLevel]:
        with Session(self._engine) as session:
            return [
                IndexLevel(series=r.series, month=r.month, level=r.level)
                for r in session.scalars(select(PriceIndexRecord).order_by(PriceIndexRecord.id))
            ]


def _portfolio_key(portfolio: Portfolio) -> tuple[str, str]:
    """What identifies a Portfolio."""
    return (portfolio.platform, portfolio.key)


def _store_portfolios(session: Session, rows: Rows) -> dict[tuple[str, str], int]:
    """Store each Portfolio of `rows` not stored yet, rename those stored under another name, and return the id of
    each by its (platform, key)."""
    platforms = dict(session.execute(select(PlatformRecord.code, PlatformRecord.id)).all())
    dated = [*rows.deposits, *rows.purchases, *rows.sales, *rows.fees, *rows.conversions]
    # The name in the latest row wins.
    latest = {_portfolio_key(r.portfolio): r.portfolio for r in sorted(dated, key=lambda r: r.day)}
    ids = {}
    for key, portfolio in latest.items():
        platform_id = platforms[portfolio.platform]
        record = session.scalars(
            select(PortfolioRecord).where(PortfolioRecord.platform_id == platform_id, PortfolioRecord.key == key[1])
        ).one_or_none()
        if record is None:
            record = PortfolioRecord(platform_id=platform_id, key=portfolio.key, name=portfolio.name)
            session.add(record)
            session.flush()
        record.name = portfolio.name
        ids[key] = record.id
    return ids


def _store_funds(session: Session, rows: Rows) -> dict[str, int]:
    """Store each Fund of `rows` not stored yet, rename those stored under another name, and return the id of each by
    its ISIN."""
    ids = {}
    for isin, fund in rows.funds().items():
        record = session.scalars(select(FundRecord).where(FundRecord.isin == isin)).one_or_none()
        if record is None:
            record = FundRecord(isin=isin, name=fund.name)
            session.add(record)
            session.flush()
        record.name = fund.name
        ids[isin] = record.id
    return ids
