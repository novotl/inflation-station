from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from inflation_station.purchase import Purchase
from inflation_station.store import PurchaseRecord, Store, database_url, engine

if TYPE_CHECKING:
    from pathlib import Path

PURCHASE = Purchase(
    platform="jt",
    account_id="123",
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
