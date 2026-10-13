from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from inflation_station import portu
from inflation_station.cli import main
from inflation_station.ledger import BUY, DEPOSIT, FEE, FOREX_BUY, FOREX_SELL, SELL
from inflation_station.store import Store
from inflation_station.valuation import NO_PRICES, Account, Holding, timeline

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "portu_export.csv"
JT_EXPORT = FIXTURES / "jt_export.csv"
ACCOUNT = "Moje portfolio"
SXR7, ZPRS, CSPX = "IE00B53QG562", "IE00BCBJG560", "IE00B5BMR087"


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def rows(path: Path = EXPORT) -> list[str]:
    """The export's lines, header first."""
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def write(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_import_reports_ledger_entries_added(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, "18 ledger entries added, 0 already present.\n", "")


def test_reimporting_the_same_export_adds_nothing(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, "0 ledger entries added, 18 already present.\n", "")


def test_a_later_full_history_export_adds_only_the_new_rows(tmp_path: Path) -> None:
    # The same export taken before 15 Apr: its newest four rows weren't there yet.
    earlier = write(tmp_path / "earlier.csv", rows()[:1] + rows()[5:])
    run("--data-dir", tmp_path, "import", earlier)

    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, "4 ledger entries added, 14 already present.\n", "")


def test_an_exact_repeat_is_its_own_row(tmp_path: Path) -> None:
    lines = rows()
    repeated_buy = next(n for n, line in enumerate(lines) if f"Nákup{portu.TYPE_SEPARATOR}ZPRS GY" in line)
    # The same export taken when only the first of the two identical ZPRS buys was there.
    run(
        "--data-dir", tmp_path, "import", write(tmp_path / "once.csv", lines[:repeated_buy] + lines[repeated_buy + 1 :])
    )

    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, "1 ledger entries added, 17 already present.\n", "")
    assert sum(e.units for e in Store(tmp_path).ledger() if e.isin == ZPRS) == Decimal("0.7500")


def test_the_account_is_the_portfolio_name_so_a_renamed_portfolio_is_a_new_account(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    renamed = write(tmp_path / "renamed.csv", [line.replace(f";{ACCOUNT};", ";Důchod;") for line in rows()])

    assert run("--data-dir", tmp_path, "import", renamed) == (0, "18 ledger entries added, 0 already present.\n", "")
    assert {(e.platform, e.account_id) for e in Store(tmp_path).ledger()} == {("portu", ACCOUNT), ("portu", "Důchod")}


def test_rows_are_read_by_type(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    entries = sorted(Store(tmp_path).ledger(), key=lambda e: (e.day, e.source_row_id))
    assert [(e.day, e.kind, e.amount, e.currency) for e in entries if e.kind in {DEPOSIT, FEE}] == [
        (date(2021, 3, 1), DEPOSIT, Decimal("10000.00"), "CZK"),
        (date(2021, 4, 1), FEE, Decimal("-25.00"), "CZK"),
        (date(2021, 5, 3), DEPOSIT, Decimal("5000.00"), "CZK"),
    ]
    assert [
        (e.day, e.kind, e.isin, e.fund_name, e.units, e.unit_price, e.amount, e.currency)
        for e in entries
        if e.isin == ZPRS
    ] == [
        (date(2021, 3, 3), BUY, ZPRS, "ZPRS GY", Decimal("0.5000"), Decimal("80.0000"), Decimal("-40.00"), "EUR"),
        (date(2021, 3, 3), BUY, ZPRS, "ZPRS GY", Decimal("0.5000"), Decimal("80.0000"), Decimal("-40.00"), "EUR"),
        (date(2021, 4, 15), SELL, ZPRS, "ZPRS GY", Decimal("-0.2500"), Decimal("84.0000"), Decimal("21.00"), "EUR"),
    ]
    forex = [(e.day, e.kind, e.amount, e.currency) for e in entries if e.kind in {FOREX_BUY, FOREX_SELL}]
    assert sorted(forex)[:2] == [
        (date(2021, 3, 2), FOREX_BUY, Decimal("100.00"), "USD"),
        (date(2021, 3, 2), FOREX_BUY, Decimal("200.00"), "EUR"),
    ]
    assert len(forex) == 10  # noqa: PLR2004 - the fixture's forex rows
    assert all((e.isin, e.units, e.unit_price) == ("", Decimal(0), None) for e in entries if e.kind not in {BUY, SELL})


def test_unknown_row_type_fails_naming_it_and_imports_nothing(tmp_path: Path) -> None:
    lines = rows()
    dividend = f"10.04.2021;{ACCOUNT};Dividenda{portu.TYPE_SEPARATOR}CSPX LN;CSPX LN;{CSPX};;;;1,20;USD;0,18;1,38\n"
    export = write(tmp_path / "dividend.csv", [lines[0], lines[1], dividend, *lines[2:]])

    assert run("--data-dir", tmp_path, "import", JT_EXPORT, export) == (
        1,
        "",
        "Error: dividend.csv row 3: unknown type 'Dividenda'\n",
    )
    assert run("--data-dir", tmp_path, "import", JT_EXPORT)[1] == "7 Purchases added, 0 already present.\n"


@pytest.mark.parametrize(
    ("original", "broken", "error"),
    [
        ("03.05.2021;", "2021-05-03;", "portu_export.csv row 2: Datum '2021-05-03' is not a date like '31.12.2021'"),
        (";-25,00;", ";-25,0x0;", "portu_export.csv row 6: Hodnota '-25,0x0' is not a number like '1 501,01'"),
        (
            ";0,2500;;84,0000;",
            ";;;84,0000;",
            "portu_export.csv row 5: Kusy / Pozice '' is not a number like '1 501,01'",
        ),
        (
            "ZPRS GY;IE00BCBJG560;0,2500",
            "ZPRS GY;;0,2500",
            "portu_export.csv row 5: a Prodej row has no ISIN",
        ),
        (
            ";5\u00a0000,00;CZK;",
            ";5\u00a0000,00;EUR;",
            "portu_export.csv row 2: a Vklad z bankovního účtu row is in 'EUR', expected 'CZK'",
        ),
        ("Kusy / Pozice", "Kusy", "portu_export.csv is not a Portu export: missing columns Kusy / Pozice"),
    ],
)
def test_malformed_export_fails_naming_the_problem(tmp_path: Path, original: str, broken: str, error: str) -> None:
    export = tmp_path / "portu_export.csv"
    export.write_text(EXPORT.read_text(encoding="utf-8").replace(original, broken, 1), encoding="utf-8")

    assert run("--data-dir", tmp_path, "import", export) == (1, "", f"Error: {error}\n")


def test_portu_and_jt_exports_import_together(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", JT_EXPORT, EXPORT) == (
        0,
        "7 Purchases added, 0 already present.\n18 ledger entries added, 0 already present.\n",
        "",
    )


def test_cash_replays_to_the_exports_final_balances() -> None:
    t = timeline([], ledger=portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert {currency: cash[-1] for currency, cash in t.cash.items()} == {
        "CZK": Decimal("8116.00"),
        "EUR": Decimal("0.00"),
        "USD": Decimal("0.00"),
    }
    # The hedging swap's USD leg went out on 17 Mar and came back on 18 Mar.
    assert t.cash["USD"][t.dates.index(date(2021, 3, 17))] == Decimal("-50.00")


def test_units_held_go_up_on_buys_and_down_on_sells() -> None:
    t = timeline([], ledger=portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert {holding.isin: units[-1] for holding, units in t.units_held.items()} == {
        CSPX: Decimal("0.2500"),
        SXR7: Decimal("1.0000"),
        ZPRS: Decimal("0.7500"),
    }
    assert {holding.account for holding in t.units_held} == {Account("portu", ACCOUNT)}
    assert t.units_held[Holding(Account("portu", ACCOUNT), ZPRS)][t.dates.index(date(2021, 4, 14))] == Decimal("1.0000")


def test_the_deposits_are_the_amount_invested() -> None:
    t = timeline([], ledger=portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert t.dates[0] == date(2021, 3, 1)
    assert t.amount_invested[0] == t.amount_invested[-2] == Decimal("10000.00")
    assert t.amount_invested[-1] == Decimal("15000.00")


def test_chart_names_portu_funds_as_having_no_prices(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    code, out, err = run("--data-dir", tmp_path, "chart")
    assert (code, out) == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    assert err == (
        f"Not valued ({NO_PRICES}; run inflation-station fetch-prices): "
        f"SXR7 GY ({SXR7}), CSPX LN ({CSPX}), ZPRS GY ({ZPRS})\n"
    )
