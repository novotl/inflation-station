from datetime import date
from decimal import Decimal

from inflation_station.purchase import Purchase
from inflation_station.valuation import timeline


def purchase(trade_date: date, gross_czk: str, isin: str = "LU1756523376") -> Purchase:
    return Purchase(
        platform="jt",
        account_id="900000001",
        source_row_id=f"{isin}-{trade_date}",
        isin=isin,
        fund_name="Fund",
        trade_date=trade_date,
        units=Decimal(1),
        unit_price=Decimal(1),
        unit_price_currency="CZK",
        gross_czk=Decimal(gross_czk),
        fee=Decimal(0),
        fee_currency="CZK",
    )


def test_timeline_has_every_day_from_the_first_trade_date_to_today() -> None:
    t = timeline([purchase(date(2021, 6, 15), "100"), purchase(date(2021, 6, 13), "100")], today=date(2021, 6, 17))

    assert t.dates == (date(2021, 6, 13), date(2021, 6, 14), date(2021, 6, 15), date(2021, 6, 16), date(2021, 6, 17))


def test_amount_invested_steps_up_on_each_trade_date_by_the_gross_czk_amount() -> None:
    t = timeline(
        [
            purchase(date(2021, 6, 13), "8000.00"),
            purchase(date(2021, 6, 15), "5000.00"),
            purchase(date(2021, 6, 15), "1234.56", isin="LU0260870158"),
        ],
        today=date(2021, 6, 17),
    )

    assert t.amount_invested == (
        Decimal("8000.00"),
        Decimal("8000.00"),
        Decimal("14234.56"),
        Decimal("14234.56"),
        Decimal("14234.56"),
    )
