from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from click.testing import CliRunner
from fpdf import FPDF
from pypdf import PdfWriter

from inflation_station.cli import main
from inflation_station.domain import Conversion, Fund, Platform, Portfolio
from inflation_station.settings import Settings
from inflation_station.store import Base, Store, database_url, engine

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "jt_export.csv"
INVESTIKA_CASH = FIXTURES / "investika" / "cash.pdf"
INVESTIKA_HOLDINGS = FIXTURES / "investika" / "holdings.pdf"
INVESTIKA_ADDED = (
    "3 Deposits added, 0 already present.\n2 Purchases added, 0 already present.\n2 Fees added, 0 already present.\n"
)
REPO_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
# One Portfolio per Fund bought in J&T portfolio 900000001.
WORLD_FUND = Portfolio(Platform.JT, "900000001 LU1756523376", "FF - World Fund A-ACC-CZK")
PIONEER_FUND = Portfolio(Platform.JT, "900000001 LU1883872332", "AMUNDI FUNDS US PIONEER FUND - A EUR (C)")
# What importing the J&T fixture reports the first time, and again: a Deposit paid for each Purchase, and a
# Conversion for each Purchase priced in EUR.
JT_ADDED = (
    "7 Deposits added, 0 already present.\n"
    "7 Purchases added, 0 already present.\n7 Fees added, 0 already present.\n3 Conversions added, 0 already present.\n"
)
JT_PRESENT = (
    "0 Deposits added, 7 already present.\n"
    "0 Purchases added, 7 already present.\n0 Fees added, 7 already present.\n0 Conversions added, 3 already present.\n"
)


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def test_import_reports_purchases_added(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT) == (
        0,
        JT_ADDED,
        "",
    )


def test_jt_row_with_a_fee_imports_as_the_purchase_of_its_units_plus_a_fee(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    rows = Store(tmp_path).rows()
    purchase = next(p for p in rows.purchases if p.source_row_id == "900100003")
    fee = next(f for f in rows.fees if f.source_row_id == "900100003")
    # The row paid 8 000 CZK with a 231.24 CZK fee.
    assert (purchase.portfolio, purchase.fund, purchase.currency, purchase.amount) == (
        WORLD_FUND,
        Fund("LU1756523376", "FF - World Fund A-ACC-CZK"),
        "CZK",
        Decimal("7768.76"),
    )
    assert (fee.portfolio, fee.day, fee.amount, fee.currency) == (
        WORLD_FUND,
        date(2021, 6, 15),
        Decimal("231.24"),
        "CZK",
    )


def test_jt_row_priced_in_eur_imports_as_a_fee_a_conversion_and_a_purchase_in_eur(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    rows = Store(tmp_path).rows()
    # The row paid 5 000 CZK with a 145.63 CZK fee, and bought 12.07 units at 15.52 EUR for 187.34 EUR.
    assert next(c for c in rows.conversions if c.source_row_id == "900100004:conversion") == Conversion(
        PIONEER_FUND, "900100004:conversion", date(2021, 6, 15), Decimal("4854.37"), "CZK", Decimal("187.34"), "EUR"
    )
    purchase = next(p for p in rows.purchases if p.source_row_id == "900100004")
    assert (purchase.units, purchase.unit_price, purchase.currency, purchase.amount) == (
        Decimal("12.07"),
        Decimal("15.52"),
        "EUR",
        Decimal("187.34"),
    )
    assert next(f.amount for f in rows.fees if f.source_row_id == "900100004") == Decimal("145.63")


def test_each_jt_purchase_its_fee_and_its_conversion_add_up_to_the_payment(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    rows = Store(tmp_path).rows()
    paid: dict[str, Decimal] = {}
    for p in rows.purchases:
        if p.currency == "CZK":
            paid[p.source_row_id] = paid.get(p.source_row_id, Decimal(0)) + p.amount
    for c in rows.conversions:
        source_row_id = c.source_row_id.removesuffix(":conversion")
        paid[source_row_id] = paid.get(source_row_id, Decimal(0)) + c.from_amount
    for f in rows.fees:
        paid[f.source_row_id] += f.amount
    # The export's Objem v měně platby, so amount invested and inflation hurdles count what they did before.
    assert paid == {
        "900100003": Decimal(8000),
        "900100004": Decimal(5000),
        "900100006": Decimal(5000),
        "900100007": Decimal(8000),
        "900100008": Decimal(5000),
        "900100011": Decimal(100000),
        "900100013": Decimal(104000),
    }


def test_jt_export_imports_a_portfolio_per_fund_bought_in_each_jt_portfolio(tmp_path: Path) -> None:
    export = tmp_path / "jt_export.csv"
    # Move one World Fund Purchase, and the Deposit paying for it, to another J&T portfolio.
    export.write_text(
        EXPORT.read_text(encoding="utf-8")
        .replace("900100007;900000001", "900100007;900000002")
        .replace("900100009;900000001", "900100009;900000002"),
        encoding="utf-8",
    )
    run("--data-dir", tmp_path, "import", export)

    rows = Store(tmp_path).rows()
    assert sorted({(p.portfolio.key, p.portfolio.name) for p in rows.purchases}) == [
        ("900000001 CZ0008473808", "J&T MONEY A CZK OPF"),
        ("900000001 LU0260870158", "FTIF-Franklin Technology Fund-A(acc)EUR"),
        ("900000001 LU1756523376", "FF - World Fund A-ACC-CZK"),
        ("900000001 LU1883872332", "AMUNDI FUNDS US PIONEER FUND - A EUR (C)"),
        ("900000002 LU1756523376", "FF - World Fund A-ACC-CZK"),
    ]
    assert {(p.portfolio.key, p.source_row_id) for p in rows.purchases if p.portfolio.key.startswith("900000002")} == {
        ("900000002 LU1756523376", "900100007")
    }


def test_each_jt_deposit_goes_to_the_portfolio_of_the_purchase_it_paid_for(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    deposits = sorted(
        (d.source_row_id, d.portfolio.key, d.day, d.amount, d.currency) for d in Store(tmp_path).rows().deposits
    )
    assert deposits == [
        # Paid 8 000 CZK and 5 000 CZK, settling the Purchases traded three days before.
        ("900100001", "900000001 LU1756523376", date(2021, 6, 18), Decimal(8000), "CZK"),
        ("900100002", "900000001 LU1883872332", date(2021, 6, 18), Decimal(5000), "CZK"),
        ("900100005", "900000001 LU0260870158", date(2021, 6, 17), Decimal(5000), "CZK"),
        ("900100009", "900000001 LU1756523376", date(2021, 5, 21), Decimal(8000), "CZK"),
        ("900100010", "900000001 LU0260870158", date(2021, 5, 21), Decimal(5000), "CZK"),
        ("900100012", "900000001 CZ0008473808", date(2021, 5, 4), Decimal(100000), "CZK"),
        ("900100014", "900000001 LU1756523376", date(2021, 5, 3), Decimal(104000), "CZK"),
    ]


def test_jt_row_with_a_zero_fee_imports_without_a_fee(tmp_path: Path) -> None:
    export = tmp_path / "jt_export.csv"
    # A zero fee has no currency to check.
    export.write_text(EXPORT.read_text(encoding="utf-8").replace('"231,24";CZK', '",00";', 1), encoding="utf-8")

    assert run("--data-dir", tmp_path, "import", export) == (
        0,
        JT_ADDED.replace("7 Fees", "6 Fees"),
        "",
    )
    rows = Store(tmp_path).rows()
    assert next(p for p in rows.purchases if p.source_row_id == "900100003").amount == Decimal("8000.00")
    assert "900100003" not in {f.source_row_id for f in rows.fees}


def test_jt_deposit_with_no_purchase_to_pair_with_fails_naming_the_row_and_imports_nothing(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", FIXTURES / "jt_export_cash_deposits.csv") == (
        1,
        "",
        (
            "Error: jt_export_cash_deposits.csv row 2 (ID pohybu 900100001): no Purchase paid 8000.00 CZK "
            "in J&T portfolio 900000001 within 7 days of this Deposit, so its Portfolio is unknown\n"
        ),
    )

    _, out, _ = run("--data-dir", tmp_path, "import", EXPORT)
    assert out == JT_ADDED


@pytest.mark.parametrize(
    ("deposited", "exit_code"),
    [
        # J&T now takes the Deposit before the trade, and used to settle after it: up to 7 days either way.
        ("28.04.2021", 0),
        ("21.04.2021", 0),
        ("20.04.2021", 1),
        ("05.05.2021", 0),
        ("06.05.2021", 1),
    ],
)
def test_jt_deposit_pairs_with_a_purchase_traded_within_a_week_of_it(
    tmp_path: Path, deposited: str, exit_code: int
) -> None:
    export = tmp_path / "jt_export.csv"
    # Move the Deposit paying for the 104 000 CZK Purchase traded on 28.04.2021.
    export.write_text(
        EXPORT.read_text(encoding="utf-8").replace("00:00 03.05.2021;;Vklad", f"00:00 {deposited};;Vklad"),
        encoding="utf-8",
    )

    assert run("--data-dir", tmp_path, "import", export)[0] == exit_code
    if exit_code == 0:
        deposit = next(d for d in Store(tmp_path).rows().deposits if d.source_row_id == "900100014")
        assert deposit.portfolio == WORLD_FUND


def test_jt_deposit_not_in_czk_is_not_implemented(tmp_path: Path) -> None:
    export = tmp_path / "jt_export.csv"
    export.write_text(
        EXPORT.read_text(encoding="utf-8").replace(
            ';;;;"5 000,00";CZK;;;;900100002', ';;;;"5 000,00";EUR;;;;900100002'
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["--data-dir", str(tmp_path), "import", str(export)])

    assert isinstance(result.exception, NotImplementedError)
    assert "900100002" in str(result.exception)


def test_deposit_row_carrying_an_isin_is_an_unknown_movement_type(tmp_path: Path) -> None:
    transfer = tmp_path / "transfer.csv"
    # Put an ISIN on the first cash deposit row.
    transfer.write_text(
        EXPORT.read_text(encoding="utf-8").replace(
            ';;;;"8 000,00";CZK;;;;900100001', ';;;;"8 000,00";CZK;LU1756523376;;;900100001', 1
        ),
        encoding="utf-8",
    )

    assert run("--data-dir", tmp_path, "import", transfer) == (
        1,
        "",
        (
            "Error: transfer.csv row 2 (ID pohybu 900100001): "
            "unknown movement type 'Vklad - vyrovnání nákupu CP klienta - Vklad pro obchod'\n"
        ),
    )


def test_reimporting_the_same_export_adds_nothing(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "import", EXPORT) == (
        0,
        JT_PRESENT,
        "",
    )


def test_importing_an_overlapping_export_adds_only_new_purchases(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "import", FIXTURES / "jt_export_overlap.csv") == (
        0,
        (
            "2 Deposits added, 3 already present.\n"
            "2 Purchases added, 3 already present.\n2 Fees added, 3 already present.\n"
            "1 Conversions added, 2 already present.\n"
        ),
        "",
    )


def test_unknown_movement_type_fails_naming_the_row_and_imports_nothing(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", FIXTURES / "jt_export_unknown_movement.csv") == (
        1,
        "",
        (
            "Error: jt_export_unknown_movement.csv row 3 (ID pohybu 900109999): "
            "unknown movement type 'Zpětný odkup klienta (výběr)'\n"
        ),
    )

    # The file's valid Purchase row was not stored either.
    _, out, _ = run("--data-dir", tmp_path, "import", EXPORT)
    assert out == JT_ADDED


@pytest.mark.parametrize(
    ("original", "broken", "error"),
    [
        (
            '"1 436,00";CZK',
            '"1 436,00";Kč',
            (
                "jt_export.csv row 4 (ID pohybu 900100003): "
                "Měna kusové hodnoty (v měně obchodu) 'Kč' is not an ISO 4217 currency code\n"
            ),
        ),
        (
            '"187,34";EUR',
            '"187,34";CZK',
            (
                "jt_export.csv row 5 (ID pohybu 900100004): Měna objemu obchodu (v měně obchodu) is 'CZK', "
                "expected 'EUR' like Měna kusové hodnoty (v měně obchodu)\n"
            ),
        ),
        (
            '"5,41"',
            '"5,4x1"',
            "jt_export.csv row 4 (ID pohybu 900100003): Počet ks '5,4x1' is not a number like '1 501,01'\n",
        ),
        (
            "00:00 15.06.2021",
            "15.06.2021",
            (
                "jt_export.csv row 4 (ID pohybu 900100003): "
                "Datum a čas zobchodování '15.06.2021' is not a date like '00:00 31.12.2021'\n"
            ),
        ),
        (
            '"231,24";CZK',
            '"231,24";EUR',
            "jt_export.csv row 4 (ID pohybu 900100003): fee currency is 'EUR', expected 'CZK'\n",
        ),
        (
            '"-8 000,00";CZK;LU1756523376;;900200001',
            '"-8 000,00";EUR;LU1756523376;;900200001',
            "jt_export.csv row 4 (ID pohybu 900100003): payment currency is 'EUR', expected 'CZK'\n",
        ),
        ("ID pohybu", "ID", "jt_export.csv is not a J&T export: missing columns ID pohybu\n"),
    ],
)
def test_malformed_export_fails_naming_the_problem(tmp_path: Path, original: str, broken: str, error: str) -> None:
    export = tmp_path / "jt_export.csv"
    export.write_text(EXPORT.read_text(encoding="utf-8").replace(original, broken, 1), encoding="utf-8")

    assert run("--data-dir", tmp_path, "import", export) == (1, "", f"Error: {error}")


def test_missing_export_fails(tmp_path: Path) -> None:
    code, _, err = run("--data-dir", tmp_path, "import", tmp_path / "nope.csv")
    assert code == 1
    assert err.startswith(f"Error: cannot read {tmp_path / 'nope.csv'}: ")


def test_data_dir_can_be_set_by_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFLATION_STATION_DATA_DIR", str(tmp_path / "from-env"))
    run("import", EXPORT)

    _, out, _ = run("--data-dir", tmp_path / "from-env", "import", EXPORT)
    assert out == JT_PRESENT


def test_data_dir_option_overrides_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFLATION_STATION_DATA_DIR", str(tmp_path / "from-env"))
    run("--data-dir", tmp_path / "from-option", "import", EXPORT)

    _, out, _ = run("import", EXPORT)
    assert out == JT_ADDED


def test_data_dir_defaults_to_the_repos_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFLATION_STATION_DATA_DIR", raising=False)
    assert Settings(_env_file=None).data_dir == REPO_DATA_DIR


def test_data_dir_can_be_set_in_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INFLATION_STATION_DATA_DIR", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"INFLATION_STATION_DATA_DIR={tmp_path / 'from-dotenv'}\n", encoding="utf-8")

    assert Settings(_env_file=env_file).data_dir == tmp_path / "from-dotenv"


def test_migrations_match_the_models(tmp_path: Path) -> None:
    Store(tmp_path)

    with engine(database_url(tmp_path)).connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_investika_pair_imports_deposits_and_one_purchase_per_issue(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", INVESTIKA_CASH, INVESTIKA_HOLDINGS) == (
        0,
        INVESTIKA_ADDED,
        "",
    )

    rows = Store(tmp_path).rows()
    stored = {p.source_row_id: p for p in rows.purchases}
    assert sorted(stored) == ["2021-05-10T16:21:05", "2026-09-10T11:02:49"]
    issue = stored["2026-09-10T11:02:49"]
    assert (issue.portfolio, issue.fund) == (
        Portfolio(Platform.INVESTIKA, "1234567890", "1234567890"),
        Fund("CZ0008474830", "INVESTIKA realitní fond, otevřený podílový fond - Třída CZK"),
    )
    assert (issue.day, issue.units, issue.unit_price, issue.currency, issue.amount) == (
        date(2026, 8, 31),
        Decimal(2783),
        Decimal("1.7603"),
        "CZK",
        Decimal("4898.91"),
    )
    fee = next(f for f in rows.fees if f.source_row_id == "2026-09-10T11:02:49")
    assert (fee.portfolio, fee.day, fee.amount, fee.currency) == (
        issue.portfolio,
        date(2026, 8, 31),
        Decimal("101.09"),
        "CZK",
    )
    # The Deposits cover the Purchases and Fees, and the pending payment of 01.10.2026.
    assert sorted((d.day, d.amount, d.currency) for d in rows.deposits) == [
        (date(2021, 4, 19), Decimal(10200), "CZK"),
        (date(2026, 8, 3), Decimal(5000), "CZK"),
        (date(2026, 10, 1), Decimal(5000), "CZK"),
    ]
    assert {d.portfolio for d in rows.deposits} == {issue.portfolio}


def test_reimporting_investika_statements_adds_nothing(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", INVESTIKA_CASH, INVESTIKA_HOLDINGS)

    assert run("--data-dir", tmp_path, "import", INVESTIKA_HOLDINGS, INVESTIKA_CASH) == (
        0,
        (
            "0 Deposits added, 3 already present.\n"
            "0 Purchases added, 2 already present.\n0 Fees added, 2 already present.\n"
        ),
        "",
    )


def test_jt_export_and_investika_pair_import_together(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT, INVESTIKA_CASH, INVESTIKA_HOLDINGS) == (
        0,
        (
            "10 Deposits added, 0 already present.\n"
            "9 Purchases added, 0 already present.\n9 Fees added, 0 already present.\n"
            "3 Conversions added, 0 already present.\n"
        ),
        "",
    )


def test_one_investika_statement_alone_fails_and_imports_nothing(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT, INVESTIKA_CASH) == (
        1,
        "",
        (
            "Error: INVESTIKA statements come in pairs with the same Číslo smlouvy: "
            "Portfolio 1234567890 has a cash statement (cash.pdf) but no holdings statement\n"
        ),
    )

    # The J&T export given with it was not stored either.
    _, out, _ = run("--data-dir", tmp_path, "import", EXPORT)
    assert out == JT_ADDED


def test_bad_file_among_several_fails_and_imports_nothing(tmp_path: Path) -> None:
    code, _, err = run(
        "--data-dir",
        tmp_path,
        "import",
        INVESTIKA_CASH,
        INVESTIKA_HOLDINGS,
        FIXTURES / "jt_export_unknown_movement.csv",
    )
    assert code == 1
    assert err.startswith("Error: jt_export_unknown_movement.csv row 3 ")

    _, out, _ = run("--data-dir", tmp_path, "import", INVESTIKA_CASH, INVESTIKA_HOLDINGS)
    assert out == INVESTIKA_ADDED


def test_pdf_that_is_not_an_investika_statement_fails(tmp_path: Path) -> None:
    other = tmp_path / "other.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.text(15, 15, "Bank statement")
    pdf.output(str(other))

    assert run("--data-dir", tmp_path, "import", other) == (
        1,
        "",
        (
            "Error: other.pdf is not an INVESTIKA statement: "
            "its title is neither 'Pohyby na peněžním účtu' nor 'Transakce na majetkovém účtu'\n"
        ),
    )


def test_broken_pdf_fails(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really")

    code, _, err = run("--data-dir", tmp_path, "import", broken)
    assert code == 1
    assert err.startswith(f"Error: cannot read {broken}: ")


def test_pdf_with_a_blank_page_fails(tmp_path: Path) -> None:
    # Guards against pypdf changing blank-page behaviour again (<6.21 raised KeyError).
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(blank)

    assert run("--data-dir", tmp_path, "import", blank) == (
        1,
        "",
        (
            "Error: blank.pdf is not an INVESTIKA statement: "
            "its title is neither 'Pohyby na peněžním účtu' nor 'Transakce na majetkovém účtu'\n"
        ),
    )


def test_import_needs_at_least_one_file(tmp_path: Path) -> None:
    code, _, err = run("--data-dir", tmp_path, "import")
    assert code == 2  # noqa: PLR2004 - click's usage error
    assert "Missing argument 'FILES...'" in err
