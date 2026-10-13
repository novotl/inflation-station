from dataclasses import replace
from datetime import date
from decimal import Decimal

from inflation_station.fund_price import FundPrice
from inflation_station.fx_rate import FxRate
from inflation_station.ledger import BUY, DEPOSIT, FEE, FOREX_BUY, FOREX_SELL, SELL, LedgerEntry
from inflation_station.price_index import CSU_CPI, IndexLevel
from inflation_station.purchase import Purchase
from inflation_station.valuation import NO_PRICES, Account, Holding, timeline

CZK_FUND = "LU1756523376"
OTHER_CZK_FUND = "CZ0008473808"
EUR_FUND = "LU0260870158"
ETF = "IE00B53QG562"
JT = Account("jt", "900000001")
PORTU = Account("portu", "Moje portfolio")


def jt(isin: str) -> Holding:
    return Holding(JT, isin)


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
    assert t.holding_values == {jt(CZK_FUND): (Decimal(20), Decimal(20), Decimal("68.75"), Decimal("60.5"))}


def test_prices_carry_forward_over_gaps() -> None:
    t = timeline(
        [purchase(date(2021, 6, 11), "1000", units="2")],  # a Friday
        prices=[price(date(2021, 6, 11), "10"), price(date(2021, 6, 14), "11")],
        today=date(2021, 6, 14),
    )

    # Saturday and Sunday are valued at Friday's price.
    assert t.holding_values[jt(CZK_FUND)] == (Decimal(20), Decimal(20), Decimal(20), Decimal(22))


def test_a_fund_is_worth_nothing_before_its_first_purchase() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 14), "1000", isin=OTHER_CZK_FUND, units="3")],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "2", isin=OTHER_CZK_FUND)],
        today=date(2021, 6, 14),
    )

    assert t.holding_values[jt(OTHER_CZK_FUND)] == (Decimal(0), Decimal(6))


def test_a_holding_with_no_price_yet_has_no_value() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000")],
        prices=[price(date(2021, 6, 14), "10")],
        today=date(2021, 6, 14),
    )

    assert t.holding_values[jt(CZK_FUND)] == (None, Decimal(10))
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
    assert t.holding_values[jt(EUR_FUND)] == (Decimal(2040), Decimal(2091), Decimal(2091), Decimal(2184))
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

    assert t.holding_values[jt(EUR_FUND)] == (None, Decimal(1020))


def test_funds_priced_in_a_currency_without_rates_are_not_valued() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000"), purchase(date(2021, 6, 13), "1000", isin=EUR_FUND)],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "40", isin=EUR_FUND, currency="EUR")],
        rates=[rate(date(2021, 6, 13), "0.04", currency="USD")],
        today=date(2021, 6, 13),
    )

    assert set(t.holding_values) == {jt(CZK_FUND)}
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

    assert t.holding_values == {}
    assert t.not_valued == {EUR_FUND: "priced in CZK, EUR"}


def test_funds_without_prices_are_not_valued() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.holding_values == {}
    assert t.portfolio_value is None
    assert t.not_valued == {CZK_FUND: "no prices stored"}


def test_fund_names_come_from_the_purchases() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.fund_names == {CZK_FUND: f"Fund {CZK_FUND}"}


def level(month: date, value: str) -> IndexLevel:
    return IndexLevel(series=CSU_CPI, month=month, level=Decimal(value))


def test_index_levels_are_interpolated_geometrically_within_a_month() -> None:
    t = timeline(
        [purchase(date(2021, 6, 1), "1000")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "121"), level(date(2021, 8, 1), "121")],
        today=date(2021, 7, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    # 16 Jun is halfway through June's 30 days, so the index is 100 x (121 / 100) ^ 0.5 = 110: 1000 x 110 / 100.
    assert hurdle[t.dates.index(date(2021, 6, 16))] == Decimal(1100)
    assert (hurdle[0], hurdle[-1]) == (Decimal(1000), Decimal(1210))


def test_the_hurdle_grows_a_purchase_from_its_trade_date() -> None:
    t = timeline(
        [purchase(date(2021, 6, 16), "1100")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "121"), level(date(2021, 8, 1), "121")],
        today=date(2021, 7, 1),
    )

    # Bought when the index was 110, so on 1 Jul, at 121, it needs to be worth 1100 x 121 / 110.
    assert t.hurdles[CSU_CPI].values[-1] == Decimal(1210)


def test_the_hurdle_sums_every_purchase_traded_on_or_before_the_day() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000"), purchase(date(2021, 6, 1), "500", isin=OTHER_CZK_FUND)],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    assert hurdle[0] == Decimal(1000)  # the second Purchase isn't counted yet
    assert hurdle[t.dates.index(date(2021, 6, 1))] == Decimal(1100) + Decimal(500)
    assert hurdle[-1] == Decimal(1210) + Decimal(550)


def test_months_after_the_last_published_one_carry_its_month_on_month_change_forward() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000")],
        index_levels=[level(date(2021, 5, 1), "100"), level(date(2021, 6, 1), "110")],
        today=date(2021, 8, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    # June rose 10 % on May, so July is estimated at 110 x 1.1 = 121 and August at 133.1.
    assert hurdle[t.dates.index(date(2021, 7, 1))] == Decimal(1210)
    assert hurdle[-1] == Decimal(1331)


def test_the_estimate_starts_the_day_after_the_last_published_month_starts() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000")],
        index_levels=[level(date(2021, 5, 1), "100"), level(date(2021, 6, 1), "110")],
        today=date(2021, 8, 1),
    )

    # From 2 Jun on, the index lies between June's published level and July's estimated one.
    assert t.hurdles[CSU_CPI].estimated_from == date(2021, 6, 2)


def test_the_hurdle_is_unknown_before_the_first_index_level() -> None:
    t = timeline(
        [purchase(date(2021, 5, 31), "1000")],
        index_levels=[level(date(2021, 6, 1), "100"), level(date(2021, 7, 1), "110")],
        today=date(2021, 6, 1),
    )

    # Every day counts the 31 May Purchase, whose index is unknown.
    assert t.hurdles[CSU_CPI].values == (None, None)


def test_there_is_no_hurdle_without_index_levels() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.hurdles == {}


def test_units_held_are_tracked_for_every_fund_purchased_valued_or_not() -> None:
    t = timeline(
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
    t = timeline(
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
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.holding_currency_values == {}
    assert t.fund_currencies == {}


def test_amount_invested_by_fund_counts_only_that_funds_purchases() -> None:
    t = timeline(
        [
            purchase(date(2021, 6, 13), "8000.00"),
            purchase(date(2021, 6, 14), "1234.56", isin=EUR_FUND),
            purchase(date(2021, 6, 15), "5000.00"),
        ],
        today=date(2021, 6, 15),
    )

    assert t.holding_amount_invested == {
        jt(CZK_FUND): (Decimal("8000.00"), Decimal("8000.00"), Decimal("13000.00")),
        jt(EUR_FUND): (Decimal(0), Decimal("1234.56"), Decimal("1234.56")),
    }


def test_the_hurdle_by_fund_grows_only_that_funds_purchases() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000"), purchase(date(2021, 6, 1), "500", isin=OTHER_CZK_FUND)],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    czk_fund, other_fund = t.holding_hurdles[jt(CZK_FUND)][CSU_CPI], t.holding_hurdles[jt(OTHER_CZK_FUND)][CSU_CPI]
    assert (czk_fund.values[0], czk_fund.values[-1]) == (Decimal(1000), Decimal(1210))
    # Nothing is invested in the other fund before 1 Jun, so it has nothing to keep up with.
    assert (other_fund.values[0], other_fund.values[-1]) == (Decimal(0), Decimal(550))
    assert czk_fund.estimated_from == other_fund.estimated_from == t.hurdles[CSU_CPI].estimated_from


def test_there_are_no_hurdles_by_fund_without_index_levels() -> None:
    t = timeline([purchase(date(2021, 6, 13), "1000")], today=date(2021, 6, 13))

    assert t.holding_hurdles == {jt(CZK_FUND): {}}


def test_funds_without_prices_are_priced_in_the_currency_of_their_latest_purchase() -> None:
    t = timeline(
        [
            replace(purchase(date(2021, 6, 14), "1000", isin=EUR_FUND), unit_price_currency="EUR"),
            purchase(date(2021, 6, 13), "1000", isin=EUR_FUND),
            purchase(date(2021, 6, 13), "1000"),
        ],
        today=date(2021, 6, 14),
    )

    assert t.priced_in == {EUR_FUND: "EUR", CZK_FUND: "CZK"}


def test_funds_with_prices_are_priced_in_the_currencies_of_their_prices_valued_or_not() -> None:
    t = timeline(
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


def entry(day: date, kind: str, amount: str, currency: str = "CZK") -> LedgerEntry:
    """A ledger entry that moves only Cash."""
    return LedgerEntry(
        platform="portu",
        account_id="Moje portfolio",
        source_row_id=f"{day};{kind};;{amount};{currency};1",
        day=day,
        kind=kind,
        isin="",
        fund_name="",
        units=Decimal(0),
        unit_price=None,
        amount=Decimal(amount),
        currency=currency,
    )


def trade(day: date, units: str, amount: str) -> LedgerEntry:
    """A buy (units up) or sell (units down) of the EUR ETF."""
    return replace(
        entry(day, BUY if Decimal(units) > 0 else SELL, amount, currency="EUR"),
        isin=ETF,
        fund_name=f"ETF {ETF}",
        units=Decimal(units),
        unit_price=Decimal(100),
    )


def test_deposits_count_as_invested_alongside_purchases_and_fees_and_buys_do_not() -> None:
    t = timeline(
        [purchase(date(2021, 6, 14), "1000")],
        ledger=[
            entry(date(2021, 6, 13), DEPOSIT, "500"),
            trade(date(2021, 6, 14), "0.04", "-4"),
            entry(date(2021, 6, 15), FEE, "-10"),
        ],
        today=date(2021, 6, 15),
    )

    assert t.dates[0] == date(2021, 6, 13)
    assert t.amount_invested == (Decimal(500), Decimal(1500), Decimal(1500))


def test_the_hurdle_grows_each_deposit_from_its_date() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000")],
        ledger=[entry(date(2021, 6, 1), DEPOSIT, "500")],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    hurdle = t.hurdles[CSU_CPI].values
    deposited = t.dates.index(date(2021, 6, 1))
    # Before 1 Jun only the Purchase counts, so the hurdle is the fund's own.
    assert hurdle[:deposited] == t.holding_hurdles[jt(CZK_FUND)][CSU_CPI].values[:deposited]
    assert hurdle[-1] == Decimal(1210) + Decimal(550)
    # The fund's own hurdle grows only its Purchase.
    assert t.holding_hurdles[jt(CZK_FUND)][CSU_CPI].values[-1] == Decimal(1210)


def test_funds_held_in_a_managed_account_have_units_but_nothing_invested_in_them() -> None:
    t = timeline(
        [],
        ledger=[
            entry(date(2021, 6, 13), DEPOSIT, "500"),
            trade(date(2021, 6, 13), "0.04", "-4"),
            trade(date(2021, 6, 14), "-0.01", "1"),
        ],
        today=date(2021, 6, 14),
    )

    assert t.units_held == {Holding(PORTU, ETF): (Decimal("0.04"), Decimal("0.03"))}
    # A Holding in a Managed Account has nothing invested in it (ADR-0002).
    assert t.holding_amount_invested == t.holding_hurdles == {}
    assert t.fund_names == {ETF: f"ETF {ETF}"}
    assert t.priced_in == {ETF: "EUR"}
    assert t.not_valued == {ETF: NO_PRICES}


def test_cash_is_every_ledger_entry_summed_by_currency() -> None:
    t = timeline(
        [purchase(date(2021, 6, 12), "1000")],
        ledger=[
            entry(date(2021, 6, 13), DEPOSIT, "500"),
            entry(date(2021, 6, 13), FOREX_SELL, "-400"),
            entry(date(2021, 6, 13), FOREX_BUY, "16", currency="EUR"),
            trade(date(2021, 6, 14), "0.16", "-16"),
            entry(date(2021, 6, 14), FOREX_SELL, "-1", currency="EUR"),
            entry(date(2021, 6, 15), FOREX_BUY, "1", currency="EUR"),
        ],
        today=date(2021, 6, 15),
    )

    assert t.cash == {
        "CZK": (Decimal(0), Decimal(100), Decimal(100), Decimal(100)),
        "EUR": (Decimal(0), Decimal(16), Decimal(-1), Decimal(0)),
    }


def test_the_same_fund_in_two_accounts_is_two_holdings_priced_once() -> None:
    other = Account("jt", "900000002")
    t = timeline(
        [
            purchase(date(2021, 6, 13), "1000", units="2"),
            replace(purchase(date(2021, 6, 14), "300", units="3"), account_id=other.account_id),
        ],
        prices=[price(date(2021, 6, 13), "10")],
        today=date(2021, 6, 14),
    )

    assert t.units_held == {jt(CZK_FUND): (Decimal(2), Decimal(2)), Holding(other, CZK_FUND): (Decimal(0), Decimal(3))}
    assert t.holding_values == {
        jt(CZK_FUND): (Decimal(20), Decimal(20)),
        Holding(other, CZK_FUND): (Decimal(0), Decimal(30)),
    }
    assert t.holding_amount_invested == {
        jt(CZK_FUND): (Decimal(1000), Decimal(1000)),
        Holding(other, CZK_FUND): (Decimal(0), Decimal(300)),
    }
    assert t.priced_in == {CZK_FUND: "CZK"}


def test_each_account_has_the_amount_invested_and_hurdles_of_its_own_purchases_or_deposits() -> None:
    t = timeline(
        [purchase(date(2021, 5, 1), "1000")],
        ledger=[entry(date(2021, 6, 1), DEPOSIT, "500"), entry(date(2021, 6, 2), FEE, "-10")],
        index_levels=[
            level(date(2021, 5, 1), "100"),
            level(date(2021, 6, 1), "110"),
            level(date(2021, 7, 1), "121"),
            level(date(2021, 8, 1), "121"),
        ],
        today=date(2021, 7, 1),
    )

    jt_account, portu = t.accounts[JT], t.accounts[PORTU]
    assert list(t.accounts) == [JT, PORTU]
    assert (jt_account.managed, portu.managed) == (False, True)
    assert (jt_account.amount_invested[-1], portu.amount_invested[-1]) == (Decimal(1000), Decimal(500))
    assert portu.amount_invested[0] == Decimal(0)
    assert jt_account.hurdles[CSU_CPI].values[-1] == Decimal(1210)
    assert portu.hurdles[CSU_CPI].values[-1] == Decimal(550)


def test_an_accounts_value_is_its_holdings_and_its_cash_in_czk_negative_or_not() -> None:
    t = timeline(
        [purchase(date(2021, 6, 13), "1000", units="2")],
        ledger=[
            entry(date(2021, 6, 13), DEPOSIT, "500"),
            entry(date(2021, 6, 13), FOREX_SELL, "-400"),
            entry(date(2021, 6, 13), FOREX_BUY, "16", currency="EUR"),
            trade(date(2021, 6, 14), "0.16", "-16"),
            entry(date(2021, 6, 14), FOREX_SELL, "-1", currency="EUR"),
            entry(date(2021, 6, 14), FOREX_BUY, "1", currency="USD"),
        ],
        prices=[price(date(2021, 6, 13), "10"), price(date(2021, 6, 13), "100", isin=ETF, currency="EUR")],
        rates=[rate(date(2021, 6, 13), "25")],
        today=date(2021, 6, 14),
    )

    # 13 Jun: 100 CZK + 16 EUR x 25. 14 Jun: 100 CZK + 0.16 units x 100 EUR x 25 - 1 EUR x 25; USD has no rates.
    assert t.accounts[PORTU].value == (Decimal(500), Decimal(100) + Decimal(400) - Decimal(25))
    assert t.accounts[PORTU].cash["EUR"] == (Decimal(16), Decimal(-1))
    # No Cash outside Managed Accounts.
    assert t.accounts[JT].value == t.holding_values[jt(CZK_FUND)]
    assert t.accounts[JT].cash == {}


def test_an_account_none_of_whose_holdings_can_be_valued_has_no_value() -> None:
    t = timeline(
        [],
        ledger=[entry(date(2021, 6, 13), DEPOSIT, "500"), trade(date(2021, 6, 13), "0.04", "-4")],
        today=date(2021, 6, 13),
    )

    assert t.accounts[PORTU].value is None
