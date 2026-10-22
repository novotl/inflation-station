from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from inflation_station.domain import (
    CONVERSION_SUFFIX,
    Conversion,
    Deposit,
    Fee,
    Fund,
    Platform,
    Portfolio,
    Purchase,
    Rows,
    Sale,
)
from inflation_station.fx_rate import FxRate
from inflation_station.price_index import CSU_CPI, IndexLevel
from inflation_station.price_sources import FundPrice
from inflation_station.valuation import NO_PRICES, Holding, NegativeCash, timeline

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inflation_station.valuation import Timeline

CZK_FUND = "LU1756523376"
OTHER_CZK_FUND = "CZ0008473808"
EUR_FUND = "LU0260870158"
ETF = "IE00B53QG562"
JT = Portfolio(Platform.JT, "900000001", "900000001")
OTHER_JT = Portfolio(Platform.JT, "900000002", "900000002")
PORTU = Portfolio(Platform.PORTU, "Moje portfolio", "Moje portfolio")


def jt(isin: str, portfolio: Portfolio = JT) -> Holding:
    return Holding(portfolio, Fund(isin, f"Fund {isin}"))


def purchase(trade_date: date, czk: str, isin: str = CZK_FUND, units: str = "1") -> Purchase:
    """A J&T Purchase in CZK."""
    return Purchase(
        portfolio=JT,
        fund=Fund(isin, f"Fund {isin}"),
        source_row_id=f"{isin}-{trade_date}",
        day=trade_date,
        units=Decimal(units),
        unit_price=Decimal(1),
        currency="CZK",
        amount=Decimal(czk),
    )


def deposited(day: date, czk: str, portfolio: Portfolio = JT) -> Deposit:
    """A CZK Deposit into a J&T Portfolio."""
    return Deposit(portfolio, f"deposit {day} {czk}", day, Decimal(czk), "CZK")


def paid_for(*purchases: Purchase) -> list[Deposit]:
    """A Deposit of each CZK Purchase's amount on its day, so its Portfolio has no Cash left over."""
    return [Deposit(p.portfolio, f"deposit for {p.source_row_id}", p.day, p.amount, p.currency) for p in purchases]


def valued(  # noqa: PLR0913 - every input but the Purchases is keyword-only
    purchases: Sequence[Purchase] = (),
    *,
    deposits: Sequence[Deposit] = (),
    sales: Sequence[Sale] = (),
    fees: Sequence[Fee] = (),
    conversions: Sequence[Conversion] = (),
    prices: Sequence[FundPrice] = (),
    rates: Sequence[FxRate] = (),
    index_levels: Sequence[IndexLevel] = (),
    today: date,
) -> Timeline:
    """The timeline of the rows given."""
    rows = Rows(list(deposits), list(purchases), list(sales), list(fees), list(conversions))
    return timeline(rows, prices=prices, rates=rates, index_levels=index_levels, today=today)


def test_timeline_has_every_day_from_the_first_row_to_today() -> None:
    t = valued([purchase(date(2021, 6, 15), "100"), purchase(date(2021, 6, 13), "100")], today=date(2021, 6, 17))

    assert t.dates == (date(2021, 6, 13), date(2021, 6, 14), date(2021, 6, 15), date(2021, 6, 16), date(2021, 6, 17))


def test_amount_invested_steps_up_on_each_deposit_date_by_its_czk_amount() -> None:
    t = valued(
        deposits=[
            deposited(date(2021, 6, 13), "8000.00"),
            deposited(date(2021, 6, 15), "5000.00"),
            deposited(date(2021, 6, 15), "1234.56", portfolio=OTHER_JT),
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
    t = valued(
        [purchase(date(2021, 6, 13), "1000", units="2"), purchase(date(2021, 6, 15), "1500", units="3.5")],
        prices=[price(date(2021, 6, 12), "10"), price(date(2021, 6, 15), "12.5"), price(date(2021, 6, 16), "11")],
        today=date(2021, 6, 16),
    )

    #                                       13 Jun: 2 x 10    14 Jun: 2 x 10    15 Jun: 5.5 x 12.5   16 Jun: 5.5 x 11
    assert t.holding_values == {jt(CZK_FUND): (Decimal(20), Decimal(20), Decimal("68.75"), Decimal("60.5"))}


def test_prices_carry_forward_over_gaps() -> None:
    t = valued(
        [purchase(date(2021, 6, 11), "1000", units="2")],  # a Friday
        prices=[price(date(2021, 6, 11), "10"), price(date(2021, 6, 14), "11")],
        today=date(2021, 6, 14),
    )

    # Saturday and Sunday are valued at Friday's price.
    assert t.holding_values[jt(CZK_FUND)] == (Decimal(20), Decimal(20), Decimal(20), Decimal(22))


def test_a_fund_is_worth_nothing_before_its_first_purchase() -> None:
    t = valued(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 14), "1000", isin=OTHER_CZK_FUND, units="3")],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "2", isin=OTHER_CZK_FUND)],
        today=date(2021, 6, 14),
    )

    assert t.holding_values[jt(OTHER_CZK_FUND)] == (Decimal(0), Decimal(6))


def test_a_holding_with_no_price_yet_has_no_value() -> None:
    bought = purchase(date(2021, 6, 13), "1000")
    t = valued([bought], deposits=paid_for(bought), prices=[price(date(2021, 6, 14), "10")], today=date(2021, 6, 14))

    assert t.holding_values[jt(CZK_FUND)] == (None, Decimal(10))
    assert t.whole_portfolio_value == (None, Decimal(10))


def test_whole_portfolio_value_is_the_sum_of_the_fund_values() -> None:
    bought = [purchase(date(2021, 6, 13), "1000", units="2"), purchase(date(2021, 6, 14), "1000", isin=OTHER_CZK_FUND)]
    t = valued(
        bought,
        deposits=paid_for(*bought),
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "1.5", isin=OTHER_CZK_FUND)],
        today=date(2021, 6, 14),
    )

    assert t.whole_portfolio_value == (Decimal(20), Decimal("21.5"))


def rate(day: date, czk: str, currency: str = "EUR", per: int = 1) -> FxRate:
    """`per` units of `currency` cost `czk`, as ČNB quotes it."""
    return FxRate(day, currency, Decimal(per), "CZK", Decimal(czk))


def test_eur_funds_are_valued_in_czk_at_the_rate_carried_forward_over_weekends() -> None:
    t = valued(
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
    assert t.holding_values[jt(EUR_FUND)] == (Decimal(2040), Decimal(2091), Decimal(2091), Decimal(2184))
    assert t.not_valued == {}


def test_a_rate_quoted_per_100_units_values_each_unit_at_a_hundredth() -> None:
    t = valued(
        [purchase(date(2021, 6, 1), "730", isin=EUR_FUND, units="10000")],
        prices=[price(date(2021, 6, 1), "1", isin=EUR_FUND, currency="HUF")],
        rates=[rate(date(2021, 6, 1), "7.298", currency="HUF", per=100)],
        today=date(2021, 6, 1),
    )

    assert t.holding_values[jt(EUR_FUND)] == (Decimal("729.8"),)


def test_whole_portfolio_value_counts_eur_funds_in_czk() -> None:
    bought = [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)]
    t = valued(
        bought,
        deposits=paid_for(*bought),
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 11), "25.5")],
        today=date(2021, 6, 13),
    )

    assert t.whole_portfolio_value == (Decimal(1030),)


def test_a_holding_with_no_rate_yet_has_no_value() -> None:
    t = valued(
        [purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 14), "25.5")],
        today=date(2021, 6, 14),
    )

    assert t.holding_values[jt(EUR_FUND)] == (None, Decimal(1020))


def test_funds_priced_in_a_currency_without_rates_are_not_valued() -> None:
    bought = [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)]
    t = valued(
        bought,
        deposits=paid_for(*bought),
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 13), "0.04", currency="USD")],
        today=date(2021, 6, 13),
    )

    assert set(t.holding_values) == {jt(CZK_FUND)}
    assert t.whole_portfolio_value == (Decimal(10),)
    assert t.not_valued == {EUR_FUND: "no EUR rates stored"}


def test_funds_priced_in_more_than_one_currency_are_not_valued() -> None:
    t = valued(
        [purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[
            price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 14), "1000", isin=EUR_FUND, currency="CZK"),
        ],
        rates=[rate(date(2021, 6, 13), "25.5")],
        today=date(2021, 6, 14),
    )

    assert t.holding_values == {}
    assert t.not_valued == {EUR_FUND: "priced in CZK, EUR"}


def test_funds_without_prices_are_not_valued() -> None:
    t = valued([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.holding_values == {}
    # Only the Cash paid for it is valued.
    assert t.whole_portfolio_value == (Decimal(-1000),)
    assert t.not_valued == {CZK_FUND: "no prices stored"}


def test_fund_names_come_from_the_purchases() -> None:
    t = valued([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.fund_names == {CZK_FUND: f"Fund {CZK_FUND}"}


def level(month: date, value: str) -> IndexLevel:
    return IndexLevel(series=CSU_CPI, month=month, level=Decimal(value))


def test_index_levels_are_interpolated_geometrically_within_a_month() -> None:
    t = valued(
        deposits=[deposited(date(2021, 6, 1), "1000")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "121"), level(date(2021, 8, 1), "121")],
        today=date(2021, 7, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    # 16 Jun is halfway through June's 30 days, so the index is 100 x (121 / 100) ^ 0.5 = 110: 1000 x 110 / 100.
    assert hurdle[t.dates.index(date(2021, 6, 16))] == Decimal(1100)
    assert (hurdle[0], hurdle[-1]) == (Decimal(1000), Decimal(1210))


def test_the_hurdle_grows_a_deposit_from_its_date() -> None:
    t = valued(
        deposits=[deposited(date(2021, 6, 16), "1100")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "121"), level(date(2021, 8, 1), "121")],
        today=date(2021, 7, 1),
    )

    # Deposited when the index was 110, so on 1 Jul, at 121, it needs to be worth 1100 x 121 / 110.
    assert t.hurdles[CSU_CPI].values[-1] == Decimal(1210)


def test_the_hurdle_sums_every_deposit_on_or_before_the_day() -> None:
    t = valued(
        deposits=[deposited(date(2021, 5, 1), "1000"), deposited(date(2021, 6, 1), "500", portfolio=OTHER_JT)],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    assert hurdle[0] == Decimal(1000)  # the second Deposit isn't counted yet
    assert hurdle[t.dates.index(date(2021, 6, 1))] == Decimal(1100) + Decimal(500)
    assert hurdle[-1] == Decimal(1210) + Decimal(550)


def test_months_after_the_last_published_one_carry_its_month_on_month_change_forward() -> None:
    t = valued(
        deposits=[deposited(date(2021, 5, 1), "1000")],
        index_levels=[level(date(2021, 5, 1), "100"), level(date(2021, 6, 1), "110")],
        today=date(2021, 8, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    # June rose 10 % on May, so July is estimated at 110 x 1.1 = 121 and August at 133.1.
    assert hurdle[t.dates.index(date(2021, 7, 1))] == Decimal(1210)
    assert hurdle[-1] == Decimal(1331)


def test_the_estimate_starts_the_day_after_the_last_published_month_starts() -> None:
    t = valued(
        deposits=[deposited(date(2021, 5, 1), "1000")],
        index_levels=[level(date(2021, 5, 1), "100"), level(date(2021, 6, 1), "110")],
        today=date(2021, 8, 1),
    )

    # From 2 Jun on, the index lies between June's published level and July's estimated one.
    assert t.hurdles[CSU_CPI].estimated_from == date(2021, 6, 2)


def test_the_hurdle_is_unknown_before_the_first_index_level() -> None:
    t = valued(
        deposits=[deposited(date(2021, 5, 31), "1000")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "110")],
        today=date(2021, 6, 1),
    )

    # Every day counts the 31 May Deposit, whose index is unknown.
    assert t.hurdles[CSU_CPI].values == (None, None)


def test_there_is_no_hurdle_without_index_levels() -> None:
    t = valued([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.hurdles == {}


def test_units_held_are_tracked_for_every_fund_purchased_valued_or_not() -> None:
    t = valued(
        [
            purchase(date(2021, 6, 13), "1000", units="2"),
            purchase(date(2021, 6, 14), "1000", units="1.25"),
            purchase(date(2021, 6, 14), "1000", isin=EUR_FUND, units="3"),
        ],
        prices=[price(date(2021, 6, 13), "10")],
        today=date(2021, 6, 14),
    )

    assert t.units_held == {jt(CZK_FUND): (Decimal(2), Decimal("3.25")), jt(EUR_FUND): (Decimal(0), Decimal(3))}


def test_fund_currency_values_are_units_held_times_the_last_known_price() -> None:
    t = valued(
        [purchase(date(2021, 6, 11), "1000", isin=EUR_FUND, units="2"), purchase(date(2021, 6, 12), "1000")],
        prices=[
            price(date(2021, 6, 12), "40", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 14), "42", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 11), "10"),
        ],
        rates=[rate(date(2021, 6, 11), "25.5")],
        today=date(2021, 6, 14),
    )

    # Fri: no EUR price yet; Sat and Sun: 2 x 40 EUR; Mon: 2 x 42. The CZK fund is worth nothing before it's bought.
    assert t.holding_currency_values == {
        jt(EUR_FUND): (None, Decimal(80), Decimal(80), Decimal(84)),
        jt(CZK_FUND): (Decimal(0), Decimal(10), Decimal(10), Decimal(10)),
    }
    assert t.fund_currencies == {EUR_FUND: "EUR", CZK_FUND: "CZK"}


def test_funds_not_valued_have_no_fund_currency_value() -> None:
    t = valued([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.holding_currency_values == {}
    assert t.fund_currencies == {}


def test_funds_without_prices_are_priced_in_the_currency_of_their_latest_purchase() -> None:
    t = valued(
        [
            replace(purchase(date(2021, 6, 14), "1000", isin=EUR_FUND), currency="EUR"),
            purchase(date(2021, 6, 13), "1000", isin=EUR_FUND),
            purchase(date(2021, 6, 13), "1000"),
        ],
        today=date(2021, 6, 14),
    )

    assert t.priced_in == {EUR_FUND: "EUR", CZK_FUND: "CZK"}


def test_funds_with_prices_are_priced_in_the_currencies_of_their_prices_valued_or_not() -> None:
    t = valued(
        [
            purchase(date(2021, 6, 13), "1000"),
            purchase(date(2021, 6, 13), "1000", isin=EUR_FUND),
            purchase(date(2021, 6, 13), "1000", isin=OTHER_CZK_FUND),
        ],
        prices=[
            price(date(2021, 6, 13), "40", currency="EUR"),
            price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR"),
            price(date(2021, 6, 13), "1000", isin=EUR_FUND, currency="CZK"),
            price(date(2021, 6, 13), "1", isin=OTHER_CZK_FUND),
        ],
        today=date(2021, 6, 13),
    )

    # The first fund was bought in CZK but is priced in EUR, which has no rates.
    assert t.priced_in == {CZK_FUND: "EUR", EUR_FUND: "CZK, EUR", OTHER_CZK_FUND: "CZK"}


def deposit(day: date, amount: str, currency: str = "CZK") -> Deposit:
    """A Deposit into the Portu Portfolio."""
    return Deposit(PORTU, f"deposit {day} {amount}", day, Decimal(amount), currency)


def fee(on: Purchase, day: date, czk: str) -> Fee:
    """A Fee charged on `day` on a J&T Purchase."""
    return Fee(on.portfolio, on.source_row_id, day, Decimal(czk), "CZK")


def portu_fee(day: date, amount: str) -> Fee:
    return Fee(PORTU, f"fee {day} {amount}", day, Decimal(amount), "CZK")


def conversion(day: date, from_amount: str, from_currency: str, to_amount: str, to_currency: str) -> Conversion:
    """A Conversion in the Portu Portfolio."""
    return Conversion(
        PORTU, f"{day} {from_currency}", day, Decimal(from_amount), from_currency, Decimal(to_amount), to_currency
    )


def buy(day: date, units: str, amount: str) -> Purchase:
    """A Purchase of the EUR ETF in the Portu Portfolio, at 100 EUR a unit."""
    return Purchase(
        PORTU, Fund(ETF, f"ETF {ETF}"), f"{day} buy", day, Decimal(units), Decimal(100), "EUR", Decimal(amount)
    )


def sell(day: date, units: str, amount: str) -> Sale:
    """A Sale of the EUR ETF in the Portu Portfolio, at 100 EUR a unit."""
    return Sale(
        PORTU, Fund(ETF, f"ETF {ETF}"), f"{day} sell", day, Decimal(units), Decimal(100), "EUR", Decimal(amount)
    )


def test_holdings_have_units_but_nothing_invested_in_them() -> None:
    t = valued(
        [buy(date(2021, 6, 13), "0.04", "4")],
        deposits=[deposit(date(2021, 6, 13), "500")],
        sales=[sell(date(2021, 6, 14), "0.01", "1")],
        today=date(2021, 6, 14),
    )

    assert t.units_held == {Holding(PORTU, Fund(ETF, f"ETF {ETF}")): (Decimal("0.04"), Decimal("0.03"))}
    assert t.fund_names == {ETF: f"ETF {ETF}"}
    assert t.priced_in == {ETF: "EUR"}
    assert t.not_valued == {ETF: NO_PRICES}


def test_cash_is_deposits_less_purchases_less_fees_plus_sales_plus_or_minus_conversions_by_currency() -> None:
    t = valued(
        [buy(date(2021, 6, 14), "0.16", "16")],
        deposits=[deposit(date(2021, 6, 13), "500")],
        sales=[sell(date(2021, 6, 15), "0.01", "1")],
        fees=[portu_fee(date(2021, 6, 15), "10")],
        conversions=[conversion(date(2021, 6, 13), "400", "CZK", "16", "EUR")],
        today=date(2021, 6, 15),
    )

    assert t.cash == {
        "CZK": (Decimal(100), Decimal(100), Decimal(90)),
        "EUR": (Decimal(16), Decimal(0), Decimal(1)),
    }


def test_the_same_fund_in_two_portfolios_is_two_holdings_priced_once() -> None:
    t = valued(
        [
            purchase(date(2021, 6, 13), "1000", units="2"),
            replace(purchase(date(2021, 6, 14), "300", units="3"), portfolio=OTHER_JT),
        ],
        prices=[price(date(2021, 6, 13), "10")],
        today=date(2021, 6, 14),
    )

    assert t.units_held == {jt(CZK_FUND): (Decimal(2), Decimal(2)), jt(CZK_FUND, OTHER_JT): (Decimal(0), Decimal(3))}
    assert t.holding_values == {
        jt(CZK_FUND): (Decimal(20), Decimal(20)),
        jt(CZK_FUND, OTHER_JT): (Decimal(0), Decimal(30)),
    }
    assert t.priced_in == {CZK_FUND: "CZK"}


def test_each_portfolio_has_the_amount_invested_and_hurdles_of_its_own_deposits() -> None:
    bought = purchase(date(2021, 5, 1), "1000")
    t = valued(
        [bought],
        deposits=[deposited(date(2021, 5, 1), "1030"), deposit(date(2021, 6, 1), "500")],
        fees=[fee(bought, bought.day, "30"), portu_fee(date(2021, 6, 2), "10")],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    jt_portfolio, portu = t.portfolios[JT], t.portfolios[PORTU]
    assert list(t.portfolios) == [JT, PORTU]
    assert (jt_portfolio.amount_invested[-1], portu.amount_invested[-1]) == (Decimal(1030), Decimal(500))
    assert portu.amount_invested[0] == Decimal(0)
    # Each Deposit grows from its own date; the Fees count in neither.
    assert jt_portfolio.hurdles[CSU_CPI].values[-1] == Decimal("1246.3")
    assert portu.hurdles[CSU_CPI].values[-1] == Decimal(550)
    assert t.hurdles[CSU_CPI].values[-1] == Decimal("1246.3") + Decimal(550)


def test_a_portfolios_value_is_its_holdings_and_its_cash_in_czk_negative_or_not() -> None:
    bought = purchase(date(2021, 6, 13), "1000", units="2")
    t = valued(
        [bought, buy(date(2021, 6, 14), "0.16", "16")],
        deposits=[*paid_for(bought), deposit(date(2021, 6, 13), "500")],
        conversions=[
            conversion(date(2021, 6, 13), "400", "CZK", "16", "EUR"),
            conversion(date(2021, 6, 14), "1", "EUR", "1", "USD"),
        ],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "100", isin=ETF, currency="EUR")],
        rates=[rate(date(2021, 6, 13), "25")],
        today=date(2021, 6, 14),
    )

    # 13 Jun: 100 CZK + 16 EUR x 25. 14 Jun: 100 CZK + 0.16 units x 100 EUR x 25 - 1 EUR x 25; USD has no rates.
    assert t.portfolios[PORTU].value == (Decimal(500), Decimal(100) + Decimal(400) - Decimal(25))
    assert t.portfolios[PORTU].cash_not_valued == {"USD": "no USD rates stored"}
    # Its Deposit all went on its Purchase.
    assert t.portfolios[JT].value == t.holding_values[jt(CZK_FUND)]


def test_a_portfolio_has_no_value_only_when_nothing_in_it_can_be_valued() -> None:
    t = valued(
        [
            replace(purchase(date(2021, 6, 13), "40", isin=EUR_FUND), currency="EUR"),
            buy(date(2021, 6, 13), "0.04", "4"),
        ],
        deposits=[deposit(date(2021, 6, 13), "500")],
        today=date(2021, 6, 13),
    )

    # Neither fund has prices and EUR has no rates, so neither has the EUR Cash paid for it. Portu's CZK Cash can be
    # valued, as in the Whole Portfolio's value.
    assert t.portfolios[PORTU].value == t.whole_portfolio_value == (Decimal(500),)
    assert t.portfolios[JT].value is None


def test_cash_is_valued_in_czk_at_the_last_known_rate_of_each_currency() -> None:
    t = valued(
        deposits=[deposit(date(2021, 6, 11), "1000")],  # a Friday
        conversions=[
            conversion(date(2021, 6, 11), "500", "CZK", "20", "EUR"),
            conversion(date(2021, 6, 11), "200", "CZK", "10", "USD"),
        ],
        rates=[
            rate(date(2021, 6, 11), "25"),
            rate(date(2021, 6, 14), "26"),
            rate(date(2021, 6, 10), "20", currency="USD"),
        ],
        today=date(2021, 6, 14),
    )

    assert t.cash_values == {
        "CZK": (Decimal(300),) * 4,
        # Saturday and Sunday are valued at Friday's rate.
        "EUR": (Decimal(500), Decimal(500), Decimal(500), Decimal(520)),
        "USD": (Decimal(200),) * 4,
    }
    assert t.cash_value == t.whole_portfolio_value == (Decimal(1000), Decimal(1000), Decimal(1000), Decimal(1020))
    assert t.cash_not_valued == {}


def test_whole_portfolio_value_is_the_funds_plus_the_cash_so_fees_reduce_it() -> None:
    bought = purchase(date(2021, 6, 13), "1000", units="2")
    t = valued(
        [bought],
        deposits=[*paid_for(bought), deposit(date(2021, 6, 13), "500")],
        fees=[portu_fee(date(2021, 6, 14), "25")],
        prices=[price(date(2021, 6, 13), "10")],
        today=date(2021, 6, 14),
    )

    assert t.whole_portfolio_value == (Decimal(520), Decimal(495))


def test_negative_cash_is_valued_as_negative() -> None:
    t = valued(
        deposits=[deposit(date(2021, 6, 13), "1000")],
        # A hedging swap: USD the Portfolio doesn't hold sold for CZK, and bought back the next day.
        conversions=[
            conversion(date(2021, 6, 13), "50", "USD", "1000", "CZK"),
            conversion(date(2021, 6, 14), "1000", "CZK", "50", "USD"),
        ],
        rates=[rate(date(2021, 6, 13), "20", currency="USD")],
        today=date(2021, 6, 14),
    )

    assert t.cash_values["USD"] == (Decimal(-1000), Decimal(0))
    assert t.whole_portfolio_value == (Decimal(1000), Decimal(1000))


def test_cash_in_a_currency_without_rates_is_not_valued() -> None:
    t = valued(
        deposits=[deposit(date(2021, 6, 13), "1000")],
        conversions=[conversion(date(2021, 6, 13), "250", "CZK", "10", "USD")],
        rates=[rate(date(2021, 6, 13), "25")],
        today=date(2021, 6, 13),
    )

    assert set(t.cash_values) == {"CZK"}
    assert t.whole_portfolio_value == (Decimal(750),)
    assert t.cash_not_valued == {"USD": "no USD rates stored"}


def test_cash_with_no_rate_yet_has_no_value_unless_there_is_none_of_it() -> None:
    t = valued(
        deposits=[deposit(date(2021, 6, 13), "1000")],
        conversions=[
            conversion(date(2021, 6, 14), "250", "CZK", "10", "EUR"),
            conversion(date(2021, 6, 15), "10", "EUR", "250", "CZK"),
        ],
        rates=[rate(date(2021, 6, 16), "25")],
        today=date(2021, 6, 16),
    )

    assert t.cash_values["EUR"] == (Decimal(0), None, Decimal(0), Decimal(0))
    assert t.whole_portfolio_value == (Decimal(1000), None, Decimal(1000), Decimal(1000))


def test_a_fee_is_paid_from_cash_so_it_lowers_the_value_and_is_never_invested() -> None:
    bought = purchase(date(2021, 6, 15), "9708.49")
    t = valued(
        [bought],
        deposits=[deposited(date(2021, 6, 15), "10000.00")],
        fees=[fee(bought, date(2021, 6, 15), "291.51")],
        prices=[price(date(2021, 6, 15), "9708.49")],
        today=date(2021, 6, 15),
    )

    assert t.amount_invested == t.portfolios[JT].amount_invested == (Decimal("10000.00"),)
    assert t.cash == {"CZK": (Decimal("0.00"),)}
    # 9 708.49 CZK of 10 000 invested: -2.9 % on day one.
    assert t.whole_portfolio_value == t.portfolios[JT].value == (Decimal("9708.49"),)


def test_a_purchase_paid_for_by_a_conversion_leaves_no_cash_in_either_currency() -> None:
    bought = replace(purchase(date(2021, 6, 15), "391.80", isin=EUR_FUND), currency="EUR")
    paid = Conversion(
        JT, bought.source_row_id + CONVERSION_SUFFIX, bought.day, Decimal("9708.98"), "CZK", bought.amount, "EUR"
    )
    t = valued(
        [bought],
        deposits=[deposited(bought.day, "10000.00")],
        conversions=[paid],
        fees=[fee(bought, bought.day, "291.02")],
        today=date(2021, 6, 15),
    )

    assert t.amount_invested == (Decimal("10000.00"),)
    assert t.cash == {"CZK": (Decimal("0.00"),), "EUR": (Decimal("0.00"),)}
    assert t.negative_cash == ()


def test_amount_invested_is_the_deposits_and_purchases_fees_and_conversions_are_not() -> None:
    bought = purchase(date(2021, 6, 14), "1000")
    t = valued(
        [bought],
        deposits=[Deposit(JT, "jt deposit", date(2021, 6, 13), Decimal(1030), "CZK")],
        fees=[fee(bought, bought.day, "30")],
        conversions=[Conversion(JT, "swap", date(2021, 6, 15), Decimal(0), "CZK", Decimal(0), "EUR")],
        today=date(2021, 6, 15),
    )

    assert t.amount_invested == t.portfolios[JT].amount_invested == (Decimal(1030),) * 3


def test_negative_cash_in_any_currency_is_warned_about_by_portfolio_currency_and_day() -> None:
    t = valued(
        [buy(date(2021, 6, 14), "0.2", "20")],
        deposits=[deposit(date(2021, 6, 13), "1000")],
        conversions=[conversion(date(2021, 6, 16), "500", "CZK", "20", "EUR")],
        rates=[rate(date(2021, 6, 13), "25")],
        today=date(2021, 6, 17),
    )

    # 1000 CZK more than covers the 20 EUR short, but EUR Cash is still negative until it is converted.
    assert t.whole_portfolio_value is not None
    assert t.negative_cash == (NegativeCash(PORTU, "EUR", date(2021, 6, 14), date(2021, 6, 15)),)


def test_cash_that_never_goes_negative_is_not_warned_about() -> None:
    t = valued(
        [buy(date(2021, 6, 14), "0.1", "10")],
        deposits=[deposit(date(2021, 6, 13), "1000")],
        conversions=[conversion(date(2021, 6, 13), "250", "CZK", "10", "EUR")],
        today=date(2021, 6, 14),
    )

    assert t.negative_cash == ()


def test_each_stretch_of_negative_cash_is_warned_about_on_its_own() -> None:
    t = valued(
        deposits=[deposit(date(2021, 6, 13), "100")],
        conversions=[
            conversion(date(2021, 6, 13), "1", "EUR", "25", "CZK"),
            conversion(date(2021, 6, 14), "25", "CZK", "1", "EUR"),
            conversion(date(2021, 6, 16), "1", "EUR", "25", "CZK"),
        ],
        today=date(2021, 6, 17),
    )

    assert t.negative_cash == (
        NegativeCash(PORTU, "EUR", date(2021, 6, 13), date(2021, 6, 13)),
        NegativeCash(PORTU, "EUR", date(2021, 6, 16), date(2021, 6, 17)),
    )


def test_one_portfolios_cash_does_not_make_up_for_anothers_negative_cash() -> None:
    bought = purchase(date(2021, 6, 13), "1000")
    t = valued([bought], deposits=[deposit(date(2021, 6, 13), "5000")], today=date(2021, 6, 13))

    assert t.cash == {"CZK": (Decimal(4000),)}
    assert t.negative_cash == (NegativeCash(JT, "CZK", date(2021, 6, 13), date(2021, 6, 13)),)


def test_a_platform_total_adds_up_the_amounts_invested_values_and_hurdles_of_its_portfolios() -> None:
    bought = purchase(date(2021, 5, 1), "1000", units="100")
    other = replace(purchase(date(2021, 6, 1), "200", units="20"), portfolio=OTHER_JT)
    t = valued(
        [bought, other],
        deposits=[
            *paid_for(bought),
            deposited(date(2021, 6, 1), "300", portfolio=OTHER_JT),
            deposit(date(2021, 6, 1), "500"),
        ],
        prices=[price(date(2021, 5, 1), "10"), price(date(2021, 7, 1), "12")],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    assert list(t.platform_totals) == [Platform.JT, Platform.PORTU]
    jt_total = t.platform_totals[Platform.JT]
    assert jt_total.amount_invested[-1] == Decimal(1300)
    # 120 units at 12 CZK, and 100 CZK of Cash left over in the other J&T Portfolio.
    assert jt_total.value is not None
    assert jt_total.value[-1] == Decimal(1540)
    # 1 000 CZK grown from 1 May, 300 CZK from 1 Jun.
    assert jt_total.hurdles[CSU_CPI].values[-1] == Decimal(1210) + Decimal(330)
    # A Platform with one Portfolio totals that Portfolio.
    assert t.platform_totals[Platform.PORTU] == t.portfolios[PORTU]


def test_a_platform_total_has_no_value_only_when_none_of_its_portfolios_has_one() -> None:
    t = valued(
        [
            replace(purchase(date(2021, 6, 13), "40", isin=EUR_FUND), currency="EUR"),
            replace(buy(date(2021, 6, 13), "0.04", "4"), portfolio=OTHER_JT, currency="CZK"),
        ],
        deposits=[deposited(date(2021, 6, 13), "10", portfolio=OTHER_JT)],
        today=date(2021, 6, 13),
    )

    # J&T's EUR fund and EUR Cash can't be valued, but the other Portfolio's CZK Cash can.
    assert t.platform_totals[Platform.JT].value == t.portfolios[OTHER_JT].value == (Decimal(6),)
    assert t.platform_totals[Platform.JT].cash_not_valued == {"EUR": "no EUR rates stored"}
