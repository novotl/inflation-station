from datetime import date
from decimal import Decimal

from inflation_station.freshness import out_of_date
from inflation_station.fund_price import FundPrice
from inflation_station.fx_rate import FxRate
from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, IndexLevel

FUND = "LU1756523376"
NAMES = {FUND: "FF - World Fund A-ACC-CZK"}
FRIDAY = date(2021, 7, 2)


def price(day: date, isin: str = FUND) -> FundPrice:
    return FundPrice(isin=isin, day=day, price=Decimal(1), currency="CZK")


def rate(day: date) -> FxRate:
    return FxRate(currency="EUR", day=day, czk_per_unit=Decimal(25))


def level(month: date, series: str = CSU_CPI) -> IndexLevel:
    return IndexLevel(series=series, month=month, level=Decimal(100))


def test_prices_are_out_of_date_after_five_business_days_and_weekends_do_not_count() -> None:
    prices = [price(date(2021, 6, 30)), price(FRIDAY)]

    # Mon 5 Jul to Fri 9 Jul are the five business days after Friday 2 Jul.
    assert out_of_date(prices=prices, fund_names=NAMES, today=date(2021, 7, 11)) == []
    assert out_of_date(prices=prices, fund_names=NAMES, today=date(2021, 7, 12)) == [
        "FF - World Fund A-ACC-CZK (LU1756523376) prices end on 2021-07-02; run inflation-station fetch-prices"
    ]


def test_each_fund_is_judged_by_its_own_last_price() -> None:
    other = "CZ0008473808"
    prices = [price(FRIDAY), price(date(2021, 7, 9), isin=other)]

    assert out_of_date(prices=prices, fund_names={**NAMES, other: "J&T MONEY A CZK OPF"}, today=date(2021, 7, 12)) == [
        "FF - World Fund A-ACC-CZK (LU1756523376) prices end on 2021-07-02; run inflation-station fetch-prices"
    ]


def test_rates_are_out_of_date_after_five_business_days() -> None:
    rates = [rate(FRIDAY)]

    assert out_of_date(rates=rates, fund_names={}, today=date(2021, 7, 9)) == []
    assert out_of_date(rates=rates, fund_names={}, today=date(2021, 7, 12)) == [
        "EUR rates end on 2021-07-02; run inflation-station fetch-fx"
    ]


def test_an_index_is_out_of_date_once_its_next_month_should_have_been_published() -> None:
    # Each month is published by the end of the next: June 2021 by 31 Jul, so from 1 Aug May is not enough.
    levels = [level(date(2021, 4, 1)), level(date(2021, 5, 1)), level(date(2021, 5, 1), series=EUROSTAT_HICP)]

    assert out_of_date(index_levels=levels, fund_names={}, today=date(2021, 7, 31)) == []
    assert out_of_date(index_levels=levels, fund_names={}, today=date(2021, 8, 1)) == [
        "ČSÚ CPI ends with 2021-05; run inflation-station fetch-cpi",
        "Eurostat HICP ends with 2021-05; run inflation-station fetch-cpi",
    ]


def test_nothing_stored_is_nothing_out_of_date() -> None:
    assert out_of_date(fund_names=NAMES, today=FRIDAY) == []
