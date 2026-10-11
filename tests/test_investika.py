import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from inflation_station import investika
from inflation_station.errors import InflationStationError
from inflation_station.purchase import Purchase

INVESTIKA = Path(__file__).parent / "fixtures" / "investika"
FUND_NAME = "INVESTIKA realitní fond, otevřený podílový fond - Třída CZK"
ISSUES = [
    Purchase(
        platform="investika",
        account_id="1234567890",
        source_row_id="2026-09-10T11:02:49",
        isin="CZ0008474830",
        fund_name=FUND_NAME,
        trade_date=date(2026, 8, 31),
        units=Decimal(2783),
        unit_price=Decimal("1.7603"),
        unit_price_currency="CZK",
        gross_czk=Decimal("5000.00"),
        fee=Decimal("101.09"),
        fee_currency="CZK",
    ),
    Purchase(
        platform="investika",
        account_id="1234567890",
        source_row_id="2021-05-10T16:21:05",
        isin="CZ0008474830",
        fund_name=FUND_NAME,
        trade_date=date(2021, 4, 30),
        units=Decimal(7761),
        unit_price=Decimal("1.2883"),
        unit_price_currency="CZK",
        gross_czk=Decimal("10200.00"),
        fee=Decimal("201.50"),
        fee_currency="CZK",
    ),
]


def statement(fixture: str) -> investika.Statement:
    return investika.statement(fixture, (INVESTIKA / fixture).read_text(encoding="utf-8").splitlines())


def purchases(*fixtures: str) -> list[Purchase]:
    return investika.purchases([statement(f) for f in fixtures])


def fails(*fixtures: str, error: str) -> None:
    with pytest.raises(InflationStationError, match=f"^{re.escape(error)}$"):
        purchases(*fixtures)


def test_one_purchase_per_issue_with_gross_and_fee_from_the_cash_statement() -> None:
    assert purchases("cash.txt", "holdings.txt") == ISSUES


def test_the_pair_may_be_given_in_either_order() -> None:
    assert purchases("holdings.txt", "cash.txt") == ISSUES


def test_pending_payment_is_skipped() -> None:
    assert purchases("cash_pending_payment.txt", "holdings.txt") == ISSUES


def test_issue_with_no_matching_payment_fails() -> None:
    fails(
        "cash.txt",
        "holdings_unmatched_issue.txt",
        error=(
            "holdings_unmatched_issue.txt row 'Vydání CP' ordered 01.07.2026: "
            "no 'Odchozí platba z VÚ na investici' on its order date in cash.txt"
        ),
    )


def test_two_payments_on_one_order_date_fail() -> None:
    fails(
        "cash_two_payments.txt",
        "holdings.txt",
        error=(
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: "
            "2 'Odchozí platba z VÚ na investici' on its order date in cash_two_payments.txt; cannot tell which paid"
        ),
    )


def test_unknown_holdings_transaction_type_fails() -> None:
    fails(
        "cash.txt",
        "holdings_unknown_type.txt",
        error="holdings_unknown_type.txt row 'Odkup CP' ordered 20.08.2026: unknown transaction type",
    )


def test_unknown_cash_transaction_type_fails() -> None:
    fails(
        "cash_unknown_type.txt",
        "holdings.txt",
        error="cash_unknown_type.txt row 'Výplata z VÚ klientovi' on 20.09.2026: unknown transaction type",
    )


def test_mismatched_contract_numbers_fail() -> None:
    fails(
        "cash.txt",
        "holdings_other_contract.txt",
        error=(
            "Investika statements come in pairs with the same Číslo smlouvy: "
            "contract 1234567890 has a cash statement (cash.txt) but no holdings statement; "
            "contract 9876543210 has a holdings statement (holdings_other_contract.txt) but no cash statement"
        ),
    )


@pytest.mark.parametrize(
    ("fixture", "error"),
    [
        ("cash.txt", "contract 1234567890 has a cash statement (cash.txt) but no holdings statement"),
        ("holdings.txt", "contract 1234567890 has a holdings statement (holdings.txt) but no cash statement"),
    ],
)
def test_only_one_statement_of_the_pair_fails(fixture: str, error: str) -> None:
    fails(fixture, error=f"Investika statements come in pairs with the same Číslo smlouvy: {error}")


def test_two_statements_of_one_kind_for_a_contract_fail() -> None:
    fails(
        "cash.txt",
        "cash_pending_payment.txt",
        "holdings.txt",
        error=(
            "Investika statements come in pairs with the same Číslo smlouvy: "
            "contract 1234567890 has 2 cash statements (cash.txt, cash_pending_payment.txt)"
        ),
    )


def test_no_statements_give_no_purchases() -> None:
    assert investika.purchases([]) == []


def test_payment_smaller_than_the_issue_fails() -> None:
    cash = statement("cash.txt")
    lines = [line.replace("10 200,00", "9 000,00") for line in cash.lines]
    fails_with = (
        "holdings.txt row 'Vydání CP' ordered 19.04.2021: payment 9 000,00 is less than the issue's Částka 9 998,50"
    )
    with pytest.raises(InflationStationError, match=f"^{re.escape(fails_with)}$"):
        investika.purchases([investika.statement("cash.txt", lines), statement("holdings.txt")])


@pytest.mark.parametrize(
    ("original", "broken", "error"),
    [
        (
            "1,7603",
            "1,76x3",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: Cena / kus '1,76x3' is not a number like '1 501,01'",
        ),
        (
            "31.08.2026",
            "31.8.2026",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: Datum ceny '31.8.2026' is not a date like '31.12.2026'",
        ),
        (
            "31.08.2026",
            "31.02.2026",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: Datum ceny '31.02.2026' is not a date like '31.12.2026'",
        ),
        (
            "Vydání CP            2783",
            "Vydání CP            2783            x",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: has 10 columns, expected 9",
        ),
        (
            "11:02:49",
            "11:02",
            (
                "holdings.txt row 'Vydání CP' ordered 03.08.2026: "
                "its second line does not end with the currencies and the settlement time"
            ),
        ),
        (
            "19.04.2021",
            "03.08.2026",
            (
                "holdings.txt row 'Vydání CP' ordered 03.08.2026: another issue was ordered on the same day; "
                "cannot tell which 'Odchozí platba z VÚ na investici' paid for which"
            ),
        ),
        (
            "16:21:05",
            "26:21:05",
            (
                "holdings.txt row 'Vydání CP' ordered 19.04.2021: "
                "Datum vypořádání '10.05.2021' '26:21:05' is not a date and time like '31.12.2026' '23:59:59'"
            ),
        ),
        (
            "CZK            CZK ",
            "EUR            EUR ",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: Částka is in 'EUR', expected 'CZK'",
        ),
    ],
)
def test_malformed_holdings_row_fails(original: str, broken: str, error: str) -> None:
    lines = (INVESTIKA / "holdings.txt").read_text(encoding="utf-8").replace(original, broken, 1).splitlines()
    with pytest.raises(InflationStationError, match=f"^{re.escape(error)}$"):
        investika.purchases([statement("cash.txt"), investika.statement("holdings.txt", lines)])


def test_malformed_cash_amount_fails() -> None:
    lines = (INVESTIKA / "cash.txt").read_text(encoding="utf-8").replace("5 000,00 CZK", "5 000,00", 1).splitlines()
    with pytest.raises(
        InflationStationError,
        match=re.escape(
            "cash.txt row 'Odchozí platba z VÚ na investici' on 03.08.2026: "
            "Částka '5 000,00' is not an amount like '5 000,00 CZK'"
        ),
    ):
        investika.purchases([investika.statement("cash.txt", lines), statement("holdings.txt")])


def test_lines_without_a_title_are_not_a_statement() -> None:
    with pytest.raises(
        InflationStationError,
        match=re.escape(
            "x.pdf is not an Investika statement: its title is neither "
            "'Pohyby na peněžním účtu' nor 'Transakce na majetkovém účtu'"
        ),
    ):
        investika.statement("x.pdf", ["", "  Something else", "Číslo smlouvy:", "1"])


def test_statement_without_a_contract_number_fails() -> None:
    with pytest.raises(InflationStationError, match=re.escape("x.pdf has no Číslo smlouvy")):
        investika.statement("x.pdf", ["  Pohyby na peněžním účtu", ""])
