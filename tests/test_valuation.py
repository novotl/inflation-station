from datetime import date
from decimal import Decimal

from inflation_station.fund_price import FundPrice
from inflation_station.fx_rate import FxRate
from inflation_station.purchase import Purchase
from inflation_station.valuation import timeline

CZK_FUND = "LU1756523376"
OTHER_CZK_FUND = "CZ0008473808"
EUR_FUND = "LU0260870158"


def purchase(trade_date: date, gross_czk: str, isin: str = CZK_FUND, units: str = "1") -> Purchase:
    return Purchase(
        platform="jt",
        account_id="900000001",
        source_row_id=f"{isin}-{trade_date}",
        isin=isin,
        fund_name=f"Fund {isin}",
        trade_date=trade_date,
        units=Decimal(units),
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
            purchase(date(2021, 6, 15), "1234.56", isin=EUR_FUND),
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


def price(day: date, amount: str, isin: str = CZK_FUND, currency: str = "CZK") -> FundPrice:
    return FundPrice(isin=isin, day=day, price=Decimal(amount), currency=currency)


def test_units_held_accumulate_by_trade_date() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000", units="2"), purchase(date(2021, 6, 15), "1500", units="3.5")],
        prices=[price(date(2021, 6, 12), "10"), price(date(2021, 6, 15), "12.5"), price(date(2021, 6, 16), "11")],
        today=date(2021, 6, 16),
    )

    #                                       13 Jun: 2 x 10    14 Jun: 2 x 10    15 Jun: 5.5 x 12.5   16 Jun: 5.5 x 11
    assert t.fund_values == {CZK_FUND: (Decimal(20), Decimal(20), Decimal("68.75"), Decimal("60.5"))}


def test_prices_carry_forward_over_gaps() -> None:
    t = timeline(
        [purchase(date(2021, 6, 11), "1000", units="2")],  # a Friday
        prices=[price(date(2021, 6, 11), "10"), price(date(2021, 6, 14), "11")],
        today=date(2021, 6, 14),
    )

    # Saturday and Sunday are valued at Friday's price.
    assert t.fund_values[CZK_FUND] == (Decimal(20), Decimal(20), Decimal(20), Decimal(22))


def test_a_fund_is_worth_nothing_before_its_first_purchase() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 14), "1000", isin=OTHER_CZK_FUND, units="3")],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "2", isin=OTHER_CZK_FUND)],
        today=date(2021, 6, 14),
    )

    assert t.fund_values[OTHER_CZK_FUND] == (Decimal(0), Decimal(6))


def test_a_holding_with_no_price_yet_has_no_value() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000")],
        prices=[price(date(2021, 6, 14), "10")],
        today=date(2021, 6, 14),
    )

    assert t.fund_values[CZK_FUND] == (None, Decimal(10))
    assert t.portfolio_value == (None, Decimal(10))


def test_portfolio_value_is_the_sum_of_the_fund_values() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000", units="2"), purchase(date(2021, 6, 14), "1000", isin=OTHER_CZK_FUND)],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "1.5", isin=OTHER_CZK_FUND)],
        today=date(2021, 6, 14),
    )

    assert t.portfolio_value == (Decimal(20), Decimal("21.5"))


def rate(day: date, czk_per_unit: str, currency: str = "EUR") -> FxRate:
    return FxRate(currency=currency, day=day, czk_per_unit=Decimal(czk_per_unit))


def test_eur_funds_are_valued_in_czk_at_the_rate_carried_forward_over_weekends() -> None:
    t = timeline(
        [purchase(date(2021, 6, 11), "1000", isin=EUR_FUND, units="2")],  # a Friday
        prices=[
            price(date(2021, 6, 11), "40", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 12), "41", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 14), "42", isin=EUR_FUND, currency="EUR"),
        ],
        rates=[rate(date(2021, 6, 10), "25"), rate(date(2021, 6, 11), "25.5"), rate(date(2021, 6, 14), "26")],
        today=date(2021, 6, 14),
    )

    # Fri: 2 x 40 EUR x 25.5; Sat: 2 x 41 x Friday's 25.5; Sun: Saturday's price, Friday's rate; Mon: 2 x 42 x 26.
    assert t.fund_values[EUR_FUND] == (Decimal(2040), Decimal(2091), Decimal(2091), Decimal(2184))
    assert t.not_valued == {}


def test_portfolio_value_counts_eur_funds_in_czk() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 11), "25.5")],
        today=date(2021, 6, 13),
    )

    assert t.portfolio_value == (Decimal(1030),)


def test_a_holding_with_no_rate_yet_has_no_value() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 14), "25.5")],
        today=date(2021, 6, 14),
    )

    assert t.fund_values[EUR_FUND] == (None, Decimal(1020))


def test_funds_priced_in_a_currency_without_rates_are_not_valued() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 13), "0.04", currency="USD")],
        today=date(2021, 6, 13),
    )

    assert set(t.fund_values) == {CZK_FUND}
    assert t.portfolio_value == (Decimal(10),)
    assert t.not_valued == {EUR_FUND: "no EUR rates stored"}


def test_funds_priced_in_more_than_one_currency_are_not_valued() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[
            price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 14), "1000", isin=EUR_FUND, currency="CZK"),
        ],
        rates=[rate(date(2021, 6, 13), "25.5")],
        today=date(2021, 6, 14),
    )

    assert t.fund_values == {}
    assert t.not_valued == {EUR_FUND: "priced in CZK, EUR"}


def test_funds_without_prices_are_not_valued() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.fund_values == {}
    assert t.portfolio_value is None
    assert t.not_valued == {CZK_FUND: "no prices stored"}


def test_fund_names_come_from_the_purchases() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.fund_names == {CZK_FUND: f"Fund {CZK_FUND}"}
