from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from inflation_station.domain import Conversion, Deposit, Fee, Fund, Platform, Portfolio, Purchase, Rows, Sale
from inflation_station.errors import InflationStationError
from inflation_station.fx_rate import FxRate
from inflation_station.price_sources import FundPrice
from inflation_station.store import Added, DepositRecord, Store, database_url, engine

if TYPE_CHECKING:
    from pathlib import Path

JT = Portfolio(Platform.JT, "123", "123")
PORTU = Portfolio(Platform.PORTU, "Moje portfolio", "Moje portfolio")
FUND = Fund("LU1756523376", "Fund")
PURCHASE = Purchase(
    portfolio=JT,
    fund=FUND,
    source_row_id="900100001",
    day=date(2021, 6, 15),
    units=Decimal("5.4100"),
    unit_price=Decimal("1478.74"),
    currency="CZK",
    amount=Decimal("8000.00"),
)
DEPOSIT = Deposit(PORTU, "12.04.2021;Vklad z bankovního účtu;;1000;CZK;1", date(2021, 4, 12), Decimal(1000), "CZK")
FEE = Fee(JT, "900100001", date(2021, 6, 15), Decimal("291.51"), "CZK")
EVERY_KIND = Rows(
    deposits=[DEPOSIT],
    purchases=[PURCHASE],
    sales=[
        Sale(
            PORTU, Fund("IE00B53QG562", "SXR7 GY"), "s", date(2021, 4, 15), Decimal(1), Decimal(84), "EUR", Decimal(84)
        )
    ],
    fees=[FEE],
    conversions=[Conversion(PORTU, "c", date(2021, 4, 15), Decimal(21), "EUR", Decimal(546), "CZK")],
)


def test_every_kind_of_row_round_trips(tmp_path: Path) -> None:
    store = Store(tmp_path)

    assert store.add_rows(EVERY_KIND) == {
        "Deposits": Added(1, 0),
        "Purchases": Added(1, 0),
        "Sales": Added(1, 0),
        "Fees": Added(1, 0),
        "Conversions": Added(1, 0),
    }
    assert store.rows() == EVERY_KIND


def test_a_stored_row_is_identified_by_its_portfolio_and_source_row(tmp_path: Path) -> None:
    store = Store(tmp_path)
    other_portfolio = replace(FEE, portfolio=Portfolio(Platform.JT, "456", "456"))

    assert store.add_rows(Rows(fees=[FEE, other_portfolio]))["Fees"] == Added(added=2, already_present=0)
    # Storing an already-stored Fee adds nothing, even with a different amount.
    assert store.add_rows(Rows(fees=[replace(FEE, amount=Decimal(1)), other_portfolio]))["Fees"] == Added(0, 2)
    assert store.rows() == Rows(fees=[FEE, other_portfolio])


def test_a_portfolio_and_a_fund_are_stored_once_named_as_in_the_latest_import(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.add_rows(Rows(purchases=[PURCHASE]))
    renamed = replace(
        PURCHASE, source_row_id="2", portfolio=replace(JT, name="Pension"), fund=replace(FUND, name="New")
    )

    store.add_rows(Rows(purchases=[renamed]))

    assert {(p.portfolio, p.fund) for p in store.rows().purchases} == {(renamed.portfolio, renamed.fund)}
    with engine(database_url(tmp_path)).connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM portfolio")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM fund")).scalar_one() == 1


def test_the_platforms_are_the_platform_enums_members(tmp_path: Path) -> None:
    Store(tmp_path)

    with engine(database_url(tmp_path)).connect() as connection:
        assert connection.execute(text("SELECT code FROM platform ORDER BY id")).scalars().all() == list(Platform)


def test_amounts_round_trip_exactly_and_are_stored_as_text(tmp_path: Path) -> None:
    Store(tmp_path).add_rows(Rows(purchases=[PURCHASE]))

    with engine(database_url(tmp_path)).connect() as connection:
        assert connection.execute(text("SELECT units FROM purchase")).scalar_one() == "5.4100"
    assert Store(tmp_path).rows().purchases[0].units == Decimal("5.4100")


def test_an_fx_rate_is_stored_as_quoted(tmp_path: Path) -> None:
    rate = FxRate(date(2021, 6, 1), "HUF", Decimal(100), "CZK", Decimal("7.298"))
    store = Store(tmp_path)

    store.add_fx_rates([rate])

    assert store.fx_rates() == [rate]
    with engine(database_url(tmp_path)).connect() as connection:
        assert connection.execute(text("SELECT from_amount, to_amount FROM fx_rate")).one() == ("100", "7.298")


def test_a_currency_column_takes_only_three_capital_letters(tmp_path: Path) -> None:
    Store(tmp_path).add_rows(Rows(purchases=[PURCHASE]))

    with engine(database_url(tmp_path)).begin() as connection, pytest.raises(IntegrityError, match="CHECK"):
        connection.execute(text("UPDATE purchase SET currency = 'czk'"))


def test_a_price_of_a_fund_never_bought_or_sold_is_refused(tmp_path: Path) -> None:
    store = Store(tmp_path)

    with pytest.raises(ValueError, match="prices of funds never bought or sold: LU1756523376"):
        store.add_fund_prices([FundPrice("LU1756523376", date(2021, 6, 15), Decimal(1), "CZK")])


def test_a_row_of_an_unknown_portfolio_is_refused(tmp_path: Path) -> None:
    Store(tmp_path)

    with engine(database_url(tmp_path)).begin() as connection, pytest.raises(IntegrityError, match="FOREIGN KEY"):
        connection.execute(
            text(
                "INSERT INTO fee (portfolio_id, source_row_id, day, amount, currency, imported_at)"
                " VALUES (42, '1', '2021-06-15', '1', 'CZK', '2026-10-10 10:00:00.000000')"
            )
        )


def test_timestamps_are_stored_as_naive_utc_and_read_back_aware(tmp_path: Path) -> None:
    prague = timezone(timedelta(hours=2))
    Store(tmp_path).add_rows(Rows(deposits=[DEPOSIT]))
    url = database_url(tmp_path)
    with Session(engine(url)) as session, session.begin():
        session.scalars(select(DepositRecord)).one().imported_at = datetime(2026, 10, 10, 12, 0, tzinfo=prague)

    with Session(engine(url)) as session:
        assert session.scalars(select(DepositRecord.imported_at)).one() == datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        assert session.execute(text("SELECT imported_at FROM deposit")).scalar_one() == "2026-10-10 10:00:00.000000"


def test_naive_timestamps_are_rejected(tmp_path: Path) -> None:
    Store(tmp_path).add_rows(Rows(deposits=[DEPOSIT]))

    with Session(engine(database_url(tmp_path))) as session:
        session.scalars(select(DepositRecord)).one().imported_at = datetime(2026, 10, 10, 12, 0)  # noqa: DTZ001
        with pytest.raises(StatementError, match="refusing to store naive datetime"):
            session.flush()


def test_a_database_stored_before_the_normalized_schema_must_be_deleted(tmp_path: Path) -> None:
    with engine(database_url(tmp_path)).begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0008')"))

    with pytest.raises(InflationStationError, match="was stored by an older version that can't be upgraded"):
        Store(tmp_path)
