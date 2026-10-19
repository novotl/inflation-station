from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from inflation_station.ledger import DEPOSIT, LedgerEntry
from inflation_station.purchase import Purchase
from inflation_station.store import PurchaseRecord, Store, database_url, engine, migrate

if TYPE_CHECKING:
    from pathlib import Path

PURCHASE = Purchase(
    platform="jt",
    portfolio_id="123",
    source_row_id="900100001",
    isin="LU1756523376",
    fund_name="Fund",
    trade_date=date(2021, 6, 15),
    units=Decimal("5.4100"),
    unit_price=Decimal("1478.74"),
    unit_price_currency="CZK",
    gross_czk=Decimal("8000.00"),
    fee=Decimal("0.00"),
    fee_currency="CZK",
)

DEPOSIT_ENTRY = LedgerEntry(
    platform="portu",
    portfolio_id="Moje portfolio",
    source_row_id="12.04.2021;Vklad z bankovního účtu;;1000;CZK;1",
    day=date(2021, 4, 12),
    kind=DEPOSIT,
    isin="",
    fund_name="",
    units=Decimal(0),
    unit_price=None,
    amount=Decimal(1000),
    currency="CZK",
)


def test_amounts_round_trip_exactly_and_are_stored_as_text(tmp_path: Path) -> None:
    Store(tmp_path).add_purchases([PURCHASE])

    with Session(engine(database_url(tmp_path))) as session:
        assert session.scalars(select(PurchaseRecord.units)).one() == Decimal("5.4100")
        assert session.execute(text("SELECT units FROM purchase")).scalar_one() == "5.4100"


def test_timestamps_are_stored_as_naive_utc_and_read_back_aware(tmp_path: Path) -> None:
    prague = timezone(timedelta(hours=2))
    Store(tmp_path)
    url = database_url(tmp_path)
    with Session(engine(url)) as session, session.begin():
        record = PurchaseRecord(**vars(PURCHASE), imported_at=datetime(2026, 10, 10, 12, 0, tzinfo=prague))
        session.add(record)

    with Session(engine(url)) as session:
        assert session.scalars(select(PurchaseRecord.imported_at)).one() == datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
        assert session.execute(text("SELECT imported_at FROM purchase")).scalar_one() == "2026-10-10 10:00:00.000000"


def test_naive_timestamps_are_rejected(tmp_path: Path) -> None:
    Store(tmp_path)

    with Session(engine(database_url(tmp_path))) as session:
        session.add(PurchaseRecord(**vars(PURCHASE), imported_at=datetime(2026, 10, 10, 12, 0)))  # noqa: DTZ001
        with pytest.raises(StatementError, match="refusing to store naive datetime"):
            session.flush()


def test_upgrading_a_database_stored_by_account_id_keeps_every_row_under_its_portfolio(tmp_path: Path) -> None:
    url = database_url(tmp_path)
    migrate(url, "0005")
    with engine(url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO purchase (platform, account_id, source_row_id, isin, fund_name, trade_date, units,"
                " unit_price, unit_price_currency, gross_czk, fee, fee_currency, imported_at)"
                " VALUES ('jt', '123', '900100001', 'LU1756523376', 'Fund', '2021-06-15', '5.4100', '1478.74', 'CZK',"
                " '8000.00', '0.00', 'CZK', '2026-10-10 10:00:00.000000')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ledger_entry (platform, account_id, source_row_id, day, kind, isin, fund_name, units,"
                " unit_price, amount, currency, imported_at)"
                " VALUES ('portu', 'Moje portfolio', '12.04.2021;Vklad z bankovního účtu;;1000;CZK;1', '2021-04-12',"
                " 'deposit', '', '', '0', NULL, '1000', 'CZK', '2026-10-10 10:00:00.000000')"
            )
        )

    store = Store(tmp_path)

    assert store.purchases() == [PURCHASE]
    assert store.ledger() == [DEPOSIT_ENTRY]
    # Re-importing the same rows adds nothing.
    assert store.add_purchases([PURCHASE]).added == 0
    assert store.add_ledger_entries([DEPOSIT_ENTRY]).added == 0
