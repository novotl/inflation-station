import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from inflation_station import investika
from inflation_station.domain import Deposit, Fee, Fund, Platform, Portfolio, Purchase, Rows
from inflation_station.errors import InflationStationError

INVESTIKA = Path(__file__).parent / "fixtures" / "investika"
CONTRACT = Portfolio(Platform.INVESTIKA, "1234567890", "1234567890")
FUND = Fund("CZ0008474830", "INVESTIKA realitní fond, otevřený podílový fond - Třída CZK")
ISSUES = [
    Purchase(
        portfolio=CONTRACT,
        fund=FUND,
        source_row_id="2026-09-10T11:02:49",
        day=date(2026, 8, 31),
        units=Decimal(2783),
        unit_price=Decimal("1.7603"),
        currency="CZK",
        amount=Decimal("4898.91"),
    ),
    Purchase(
        portfolio=CONTRACT,
        fund=FUND,
        source_row_id="2021-05-10T16:21:05",
        day=date(2021, 4, 30),
        units=Decimal(7761),
        unit_price=Decimal("1.2883"),
        currency="CZK",
        amount=Decimal("9998.50"),
    ),
]
# The payment less the issue's Částka: the entry fee and the rounding.
FEES = [
    Fee(CONTRACT, "2026-09-10T11:02:49", date(2026, 8, 31), Decimal("101.09"), "CZK"),
    Fee(CONTRACT, "2021-05-10T16:21:05", date(2021, 4, 30), Decimal("201.50"), "CZK"),
]
# The cash statement's deposits; identical ones on one day are told apart by their count.
DEPOSITS = [
    Deposit(CONTRACT, "2026-08-03;5000.00;1", date(2026, 8, 3), Decimal(5000), "CZK"),
    Deposit(CONTRACT, "2021-04-19;10200.00;1", date(2021, 4, 19), Decimal(10200), "CZK"),
]
ROWS = Rows(deposits=DEPOSITS, purchases=ISSUES, fees=FEES)


def statement(fixture: str) -> investika.Statement:
    return investika.statement(fixture, (INVESTIKA / fixture).read_text(encoding="utf-8").splitlines())


def rows(*fixtures: str | investika.Statement) -> Rows:
    """Rows from fixture files, or from statements a test has changed."""
    return investika.rows([statement(f) if isinstance(f, str) else f for f in fixtures])


def fails(*fixtures: str | investika.Statement, error: str) -> None:
    with pytest.raises(InflationStationError, match=f"^{re.escape(error)}$"):
        rows(*fixtures)


def test_one_deposit_per_deposit_row_one_purchase_per_issue_and_a_fee_of_the_rest_of_its_payment() -> None:
    assert rows("cash.txt", "holdings.txt") == ROWS


def test_the_pair_may_be_given_in_either_order() -> None:
    assert rows("holdings.txt", "cash.txt") == ROWS


def test_pending_payment_is_skipped_but_its_deposit_is_not() -> None:
    pending = Deposit(CONTRACT, "2026-10-01;5000.00;1", date(2026, 10, 1), Decimal(5000), "CZK")
    assert rows("cash_pending_payment.txt", "holdings.txt") == Rows(
        deposits=[pending, *DEPOSITS], purchases=ISSUES, fees=FEES
    )


def test_identical_deposits_on_one_day_are_told_apart() -> None:
    cash = statement("cash.txt")
    deposit = next(line for line in cash.lines if "03.08.2026" in line and "Kredit" in line)
    got = rows(investika.statement("cash.txt", [*cash.lines, deposit]), "holdings.txt")
    assert [d.source_row_id for d in got.deposits] == [
        "2026-08-03;5000.00;1",
        "2021-04-19;10200.00;1",
        "2026-08-03;5000.00;2",
    ]


def test_non_czk_deposit_is_not_implemented() -> None:
    lines = (
        (INVESTIKA / "cash.txt")
        .read_text(encoding="utf-8")
        .replace("Kredit            5 000,00 CZK", "Kredit            200,00 EUR")
        .splitlines()
    )
    with pytest.raises(
        NotImplementedError,
        match="^"
        + re.escape(
            "cash.txt row 'Investice klienta - vklad na VÚ' on 03.08.2026: "
            "a Deposit in 'EUR'; only CZK Deposits can be imported yet"
        )
        + "$",
    ):
        investika.rows([investika.statement("cash.txt", lines), statement("holdings.txt")])


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


def test_statements_of_different_portfolios_fail() -> None:
    fails(
        "cash.txt",
        "holdings_other_contract.txt",
        error=(
            "INVESTIKA statements come in pairs with the same Číslo smlouvy: "
            "Portfolio 1234567890 has a cash statement (cash.txt) but no holdings statement; "
            "Portfolio 9876543210 has a holdings statement (holdings_other_contract.txt) but no cash statement"
        ),
    )


@pytest.mark.parametrize(
    ("fixture", "error"),
    [
        ("cash.txt", "Portfolio 1234567890 has a cash statement (cash.txt) but no holdings statement"),
        ("holdings.txt", "Portfolio 1234567890 has a holdings statement (holdings.txt) but no cash statement"),
    ],
)
def test_only_one_statement_of_the_pair_fails(fixture: str, error: str) -> None:
    fails(fixture, error=f"INVESTIKA statements come in pairs with the same Číslo smlouvy: {error}")


def test_two_statements_of_one_kind_for_a_portfolio_fail() -> None:
    fails(
        "cash.txt",
        "cash_pending_payment.txt",
        "holdings.txt",
        error=(
            "INVESTIKA statements come in pairs with the same Číslo smlouvy: "
            "Portfolio 1234567890 has 2 cash statements (cash.txt, cash_pending_payment.txt)"
        ),
    )


def test_no_statements_give_no_rows() -> None:
    assert investika.rows([]) == Rows()


def test_payment_smaller_than_the_issue_fails() -> None:
    cash = statement("cash.txt")
    lines = [line.replace("10 200,00", "9 000,00") for line in cash.lines]
    fails(
        investika.statement("cash.txt", lines),
        "holdings.txt",
        error=(
            "holdings.txt row 'Vydání CP' ordered 19.04.2021: payment 9 000,00 is less than the issue's Částka 9 998,50"
        ),
    )


def test_two_issues_settled_at_the_same_time_fail() -> None:
    holdings = statement("holdings.txt")
    lines = [line.replace("10.05.2021", "10.09.2026").replace("16:21:05", "11:02:49") for line in holdings.lines]
    fails(
        "cash.txt",
        investika.statement("holdings.txt", lines),
        error=(
            "holdings.txt row 'Vydání CP' ordered 19.04.2021: settled at 2026-09-10T11:02:49, like an earlier issue; "
            "the settlement time identifies an issue, so the import cannot tell them apart"
        ),
    )


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
        (
            "CZK            CZK ",
            "EUR            CZK ",
            "holdings.txt row 'Vydání CP' ordered 03.08.2026: Cena / kus is in 'EUR', expected 'CZK' like Částka",
        ),
    ],
)
def test_malformed_holdings_row_fails(original: str, broken: str, error: str) -> None:
    lines = (INVESTIKA / "holdings.txt").read_text(encoding="utf-8").replace(original, broken, 1).splitlines()
    with pytest.raises(InflationStationError, match=f"^{re.escape(error)}$"):
        investika.rows([statement("cash.txt"), investika.statement("holdings.txt", lines)])


def test_malformed_cash_amount_fails() -> None:
    lines = (INVESTIKA / "cash.txt").read_text(encoding="utf-8").replace("5 000,00 CZK", "5 000,00", 1).splitlines()
    with pytest.raises(
        InflationStationError,
        match=re.escape(
            "cash.txt row 'Odchozí platba z VÚ na investici' on 03.08.2026: "
            "Částka '5 000,00' is not an amount like '5 000,00 CZK'"
        ),
    ):
        investika.rows([investika.statement("cash.txt", lines), statement("holdings.txt")])


def test_lines_without_a_title_are_not_a_statement() -> None:
    with pytest.raises(
        InflationStationError,
        match=re.escape(
            "x.pdf is not an INVESTIKA statement: its title is neither "
            "'Pohyby na peněžním účtu' nor 'Transakce na majetkovém účtu'"
        ),
    ):
        investika.statement("x.pdf", ["", "  Something else", "Číslo smlouvy:", "1"])


def test_statement_without_a_portfolio_number_fails() -> None:
    with pytest.raises(InflationStationError, match=re.escape("x.pdf has no Číslo smlouvy")):
        investika.statement("x.pdf", ["  Pohyby na peněžním účtu", ""])


@pytest.mark.parametrize(
    ("original", "broken", "error"),
    [
        (
            "Debet            5 000,00 CZK",
            "Kredit            5 000,00 CZK",
            "cash.txt row 'Odchozí platba z VÚ na investici' on 03.08.2026: Typ is 'Kredit', expected 'Debet'",
        ),
        (
            "Odchozí platba z VÚ na investici            Debet",
            "Odchozí platba z VÚ na investici Debet",
            "cash.txt row on 03.08.2026: has 3 columns, expected 4 or 5",
        ),
        (
            "Kredit            5 000,00 CZK",
            "Debet            5 000,00 CZK",
            "cash.txt row 'Investice klienta - vklad na VÚ' on 03.08.2026: Typ is 'Debet', expected 'Kredit'",
        ),
        (
            "Kredit            5 000,00 CZK",
            "Kredit            5 000,x0 CZK",
            (
                "cash.txt row 'Investice klienta - vklad na VÚ' on 03.08.2026: "
                "Částka '5 000,x0' is not a number like '1 501,01'"
            ),
        ),
        (
            "Kredit            5 000,00 CZK",
            "Kredit            5 000,00",
            (
                "cash.txt row 'Investice klienta - vklad na VÚ' on 03.08.2026: "
                "Částka '5 000,00' is not an amount like '5 000,00 CZK'"
            ),
        ),
    ],
)
def test_malformed_cash_row_fails(original: str, broken: str, error: str) -> None:
    lines = (INVESTIKA / "cash.txt").read_text(encoding="utf-8").replace(original, broken, 1).splitlines()
    with pytest.raises(InflationStationError, match=f"^{re.escape(error)}$"):
        investika.rows([investika.statement("cash.txt", lines), statement("holdings.txt")])
