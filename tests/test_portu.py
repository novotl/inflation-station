from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner
from test_chart import page

from inflation_station import portu
from inflation_station.cli import main
from inflation_station.domain import Fund, Platform, Portfolio, Purchase
from inflation_station.store import Store, database_exists
from inflation_station.valuation import NO_PRICES, Holding, timeline

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "portu_export.csv"
JT_EXPORT = FIXTURES / "jt_export.csv"
PORTFOLIO = "Moje portfolio"
MOJE = Portfolio(Platform.PORTU, PORTFOLIO, PORTFOLIO)
SXR7, ZPRS, CSPX = "IE00B53QG562", "IE00BCBJG560", "IE00B5BMR087"
# What importing the fixture reports the first time, and again.
ADDED = (
    "2 Deposits added, 0 already present.\n4 Purchases added, 0 already present.\n1 Sales added, 0 already present.\n"
    "1 Fees added, 0 already present.\n5 Conversions added, 0 already present.\n"
)
PRESENT = (
    "0 Deposits added, 2 already present.\n0 Purchases added, 4 already present.\n0 Sales added, 1 already present.\n"
    "0 Fees added, 1 already present.\n0 Conversions added, 5 already present.\n"
)


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


def test_import_reports_rows_added_by_kind(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, ADDED, "")


def test_reimporting_the_same_export_adds_nothing(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "import", EXPORT) == (0, PRESENT, "")


def test_a_later_full_history_export_adds_only_the_new_rows(tmp_path: Path) -> None:
    # The same export taken before 15 Apr: its newest four rows weren't there yet.
    earlier = write(tmp_path / "earlier.csv", rows()[:1] + rows()[5:])
    run("--data-dir", tmp_path, "import", earlier)

    assert run("--data-dir", tmp_path, "import", EXPORT) == (
        0,
        (
            "1 Deposits added, 1 already present.\n0 Purchases added, 4 already present.\n"
            "1 Sales added, 0 already present.\n0 Fees added, 1 already present.\n"
            "1 Conversions added, 4 already present.\n"
        ),
        "",
    )


def test_an_exact_repeat_is_its_own_row(tmp_path: Path) -> None:
    lines = rows()
    repeated_buy = next(n for n, line in enumerate(lines) if f"Nákup{portu.TYPE_SEPARATOR}ZPRS GY" in line)
    # The same export taken when only the first of the two identical ZPRS buys was there.
    run(
        "--data-dir", tmp_path, "import", write(tmp_path / "once.csv", lines[:repeated_buy] + lines[repeated_buy + 1 :])
    )

    assert run("--data-dir", tmp_path, "import", EXPORT)[1].startswith(
        "0 Deposits added, 2 already present.\n1 Purchases added, 3 already present.\n"
    )
    stored = Store(tmp_path).rows()
    assert sum(p.units for p in stored.purchases if p.fund.isin == ZPRS) == Decimal("1.0000")


def test_the_portfolio_is_its_name_so_a_renamed_portfolio_is_a_new_portfolio(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    renamed = write(tmp_path / "renamed.csv", [line.replace(f";{PORTFOLIO};", ";Důchod;") for line in rows()])

    assert run("--data-dir", tmp_path, "import", renamed) == (0, ADDED, "")
    assert {d.portfolio for d in Store(tmp_path).rows().deposits} == {
        MOJE,
        Portfolio(Platform.PORTU, "Důchod", "Důchod"),
    }


def test_rows_are_read_by_type_with_amounts_unsigned() -> None:
    read = portu.read_export(EXPORT)

    assert [(d.day, d.amount, d.currency) for d in read.deposits] == [
        (date(2021, 3, 1), Decimal("10000.00"), "CZK"),
        (date(2021, 5, 3), Decimal("5000.00"), "CZK"),
    ]
    assert [(f.day, f.amount, f.currency) for f in read.fees] == [(date(2021, 4, 1), Decimal("25.00"), "CZK")]
    zprs = Fund(ZPRS, "ZPRS GY")
    bought = Purchase(
        MOJE,
        zprs,
        "2021-03-03;Nákup;ZPRS GY;-40.00;EUR;1",
        date(2021, 3, 3),
        Decimal("0.5000"),
        Decimal("80.0000"),
        "EUR",
        Decimal("40.00"),
    )
    # The exact repeat is told apart by its count.
    assert [p for p in read.purchases if p.fund == zprs] == [
        bought,
        replace(bought, source_row_id=bought.source_row_id[:-1] + "2"),
    ]
    assert [(s.day, s.fund, s.units, s.unit_price, s.amount, s.currency) for s in read.sales] == [
        (date(2021, 4, 15), zprs, Decimal("0.2500"), Decimal("84.0000"), Decimal("21.00"), "EUR")
    ]


def test_forex_legs_pair_into_conversions_by_day_and_currency_pair_or_detail() -> None:
    conversions = portu.read_export(EXPORT).conversions

    assert [(c.day, c.from_amount, c.from_currency, c.to_amount, c.to_currency) for c in conversions] == [
        # "CZK/USD" sold with "USD/CZK" bought, "CZK/EUR" with "EUR/CZK": two Conversions on one day.
        (date(2021, 3, 2), Decimal("5200.00"), "CZK", Decimal("200.00"), "EUR"),
        (date(2021, 3, 2), Decimal("2200.00"), "CZK", Decimal("100.00"), "USD"),
        # A swap's legs share their detail, each day's pair a Conversion of its own.
        (date(2021, 3, 17), Decimal("50.00"), "USD", Decimal("1100.00"), "CZK"),
        (date(2021, 3, 18), Decimal("1105.00"), "CZK", Decimal("50.00"), "USD"),
        (date(2021, 4, 15), Decimal("21.00"), "EUR", Decimal("546.00"), "CZK"),
    ]
    # Identified by its sell leg's row.
    assert conversions[-1].source_row_id == "2021-04-15;Forex prodej;;-21.00;EUR;1"


def test_a_forex_leg_without_exactly_one_other_fails_naming_its_row_and_imports_nothing(tmp_path: Path) -> None:
    lines = rows()
    # The EUR bought on 2 Mar, moved to the next day: neither leg has its other any more.
    moved = next(
        n
        for n, line in enumerate(lines)
        if line.startswith(f"02.03.2021;{PORTFOLIO};Forex nákup{portu.TYPE_SEPARATOR}EUR/CZK")
    )
    lines[moved] = lines[moved].replace("02.03.2021", "03.03.2021")
    export = write(tmp_path / "unpaired.csv", lines)

    assert run("--data-dir", tmp_path, "import", export) == (
        1,
        "",
        (
            "Error: unpaired.csv row 18: cannot pair the Forex prodej 'CZK/EUR' into a Conversion: that day the "
            "Portfolio has 1 Forex prodej and 0 Forex nákup rows with this detail, expected one of each\n"
        ),
    )
    assert not database_exists(tmp_path)


def test_unknown_row_type_fails_naming_it_and_imports_nothing(tmp_path: Path) -> None:
    lines = rows()
    dividend = f"10.04.2021;{PORTFOLIO};Dividenda{portu.TYPE_SEPARATOR}CSPX LN;CSPX LN;{CSPX};;;;1,20;USD;0,18;1,38\n"
    export = write(tmp_path / "dividend.csv", [lines[0], lines[1], dividend, *lines[2:]])

    assert run("--data-dir", tmp_path, "import", JT_EXPORT, export) == (
        1,
        "",
        "Error: dividend.csv row 3: unknown type 'Dividenda'\n",
    )
    assert run("--data-dir", tmp_path, "import", JT_EXPORT)[1].startswith(
        "7 Deposits added, 0 already present.\n7 Purchases added, 0 already present.\n"
    )


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
        (
            ";5\u00a0000,00;CZK;",
            ";5\u00a0000,00;Kč;",
            "portu_export.csv row 2: Měna 'Kč' is not an ISO 4217 currency code",
        ),
        (
            ";-25,00;",
            ";25,00;",
            "portu_export.csv row 6: a Poplatek row's Hodnota '25,00' is positive",
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
        (
            "9 Deposits added, 0 already present.\n11 Purchases added, 0 already present.\n"
            "1 Sales added, 0 already present.\n8 Fees added, 0 already present.\n"
            "8 Conversions added, 0 already present.\n"
        ),
        "",
    )


def test_cash_replays_to_the_exports_final_balances() -> None:
    t = timeline(portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert {currency: cash[-1] for currency, cash in t.cash.items()} == {
        "CZK": Decimal("8116.00"),
        "EUR": Decimal("0.00"),
        "USD": Decimal("0.00"),
    }
    # The hedging swap's USD leg went out on 17 Mar and came back on 18 Mar.
    assert t.cash["USD"][t.dates.index(date(2021, 3, 17))] == Decimal("-50.00")


def test_units_held_go_up_on_buys_and_down_on_sells() -> None:
    t = timeline(portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert {holding.isin: units[-1] for holding, units in t.units_held.items()} == {
        CSPX: Decimal("0.2500"),
        SXR7: Decimal("1.0000"),
        ZPRS: Decimal("0.7500"),
    }
    assert {holding.portfolio for holding in t.units_held} == {MOJE}
    assert t.units_held[Holding(MOJE, Fund(ZPRS, "ZPRS GY"))][t.dates.index(date(2021, 4, 14))] == Decimal("1.0000")


def test_the_deposits_are_the_amount_invested() -> None:
    t = timeline(portu.read_export(EXPORT), today=date(2021, 5, 3))

    assert t.dates[0] == date(2021, 3, 1)
    assert t.amount_invested[0] == t.amount_invested[-2] == Decimal("10000.00")
    assert t.amount_invested[-1] == Decimal("15000.00")


def test_chart_names_portu_funds_with_no_prices_and_cash_with_no_rates(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    code, out, err = run("--data-dir", tmp_path, "chart")
    assert (code, out) == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    assert err == (
        f"Not valued ({NO_PRICES}; run inflation-station fetch-prices): "
        f"SXR7 GY ({SXR7}), CSPX LN ({CSPX}), ZPRS GY ({ZPRS})\n"
        "Not valued (no EUR rates stored; run inflation-station fetch-fx): EUR Cash\n"
        "Not valued (no USD rates stored; run inflation-station fetch-fx): USD Cash\n"
    )


def eur_cash_export(tmp_path: Path) -> Path:
    """An export with 2 400 CZK and 100 EUR of Cash from 3 May, within the recorded EUR months, and no funds."""
    return write(
        tmp_path / "eur.csv",
        [
            rows()[0],
            "03.05.2021;Moje portfolio;Vklad z bankovního účtu;;;;;;5 000,00;CZK;;\n",
            f"03.05.2021;Moje portfolio;Forex prodej{portu.TYPE_SEPARATOR}CZK/EUR;;;;CZK/EUR;;-2 600,00;CZK;;\n",
            f"03.05.2021;Moje portfolio;Forex nákup{portu.TYPE_SEPARATOR}EUR/CZK;;;;EUR/CZK;;100,00;EUR;;\n",
        ],
    )


def test_fetch_fx_fetches_the_currencies_cash_is_held_in(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", eur_cash_export(tmp_path))

    assert run("--data-dir", tmp_path, "fetch-fx") == (0, "EUR: 44 rates added, 0 already present.\n", "")


def test_the_chart_values_cash_and_stacks_it_under_the_funds(tmp_path: Path) -> None:
    # Half an SXR7 at 3 May's close, paid from the 100 EUR.
    export = write(
        tmp_path / "eur_and_sxr7.csv",
        [
            *rows(eur_cash_export(tmp_path)),
            f"03.05.2021;{PORTFOLIO};Nákup{portu.TYPE_SEPARATOR}SXR7 GY;SXR7 GY;{SXR7};0,5000;;139,3400;-69,67;EUR;;\n",
        ],
    )
    run("--data-dir", tmp_path, "import", export)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "fetch-fx")

    assert run("--data-dir", tmp_path, "chart")[::2] == (0, "")  # nothing left out
    # On 1 Jul 2021, at ČNB's 25.505 CZK per EUR and SXR7's 30 Jun close of 143.72 EUR.
    cash = 2400 + (100 - 69.67) * 25.505
    sxr7 = 0.5 * 143.72 * 25.505
    assert page(tmp_path)["wholePortfolio"]["value"] == pytest.approx(cash + sxr7)
    stacked = page(tmp_path)["wholePortfolio"]["composition"]
    assert [(t["name"], t.get("stackgroup")) for t in stacked] == [
        ("Cash", "value"),
        ("SXR7 GY", "value"),
        ("Amount invested", None),
    ]
    assert stacked[0]["y"][-1] == pytest.approx(cash)
    assert stacked[1]["y"][-1] == pytest.approx(sxr7)


def test_fetch_fx_with_only_czk_cash_fetches_nothing(tmp_path: Path, recorded: dict[str, Path]) -> None:
    run("--data-dir", tmp_path, "import", write(tmp_path / "czk.csv", [rows()[0], rows()[-1]]))
    recorded.clear()  # any request fails the test

    assert run("--data-dir", tmp_path, "fetch-fx") == (
        0,
        "Every Purchase and all Cash is in CZK; no rates to fetch.\n",
        "",
    )
