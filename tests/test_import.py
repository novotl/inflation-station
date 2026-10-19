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
REPO_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
# What importing the J&T fixture reports the first time, and again: a Conversion paid for each Purchase priced in EUR.
JT_PORTFOLIO = Portfolio(Platform.JT, "900000001", "900000001")
JT_ADDED = (
    "7 Purchases added, 0 already present.\n7 Fees added, 0 already present.\n3 Conversions added, 0 already present.\n"
)
JT_PRESENT = (
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
        JT_PORTFOLIO,
        Fund("LU1756523376", "FF - World Fund A-ACC-CZK"),
        "CZK",
        Decimal("7768.76"),
    )
    assert (fee.portfolio, fee.day, fee.amount, fee.currency) == (
        JT_PORTFOLIO,
        date(2021, 6, 15),
        Decimal("231.24"),
        "CZK",
    )


def test_jt_row_priced_in_eur_imports_as_a_fee_a_conversion_and_a_purchase_in_eur(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    rows = Store(tmp_path).rows()
    # The row paid 5 000 CZK with a 145.63 CZK fee, and bought 12.07 units at 15.52 EUR for 187.34 EUR.
    assert next(c for c in rows.conversions if c.source_row_id == "900100004:conversion") == Conversion(
        JT_PORTFOLIO, "900100004:conversion", date(2021, 6, 15), Decimal("4854.37"), "CZK", Decimal("187.34"), "EUR"
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


def test_cash_deposit_rows_do_not_produce_purchases(tmp_path: Path) -> None:
    deposits_only = tmp_path / "deposits.csv"
    lines = EXPORT.read_text(encoding="utf-8").splitlines(keepends=True)
    deposits_only.write_text("".join(lines[:1] + [line for line in lines[1:] if ";Vklad - " in line]), encoding="utf-8")

    assert run("--data-dir", tmp_path, "import", deposits_only) == (
        0,
        "0 Purchases added, 0 already present.\n",
        "",
    )


def test_renamed_cash_deposit_rows_do_not_produce_purchases(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", FIXTURES / "jt_export_cash_deposits.csv") == (
        0,
        "0 Purchases added, 0 already present.\n",
        "",
    )


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


def test_investika_pair_imports_one_purchase_per_issue(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", INVESTIKA_CASH, INVESTIKA_HOLDINGS) == (
        0,
        "2 Purchases added, 0 already present.\n2 Fees added, 0 already present.\n",
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


def test_reimporting_investika_statements_adds_nothing(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", INVESTIKA_CASH, INVESTIKA_HOLDINGS)

    assert run("--data-dir", tmp_path, "import", INVESTIKA_HOLDINGS, INVESTIKA_CASH) == (
        0,
        "0 Purchases added, 2 already present.\n0 Fees added, 2 already present.\n",
        "",
    )


def test_jt_export_and_investika_pair_import_together(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "import", EXPORT, INVESTIKA_CASH, INVESTIKA_HOLDINGS) == (
        0,
        (
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
    assert out == "2 Purchases added, 0 already present.\n2 Fees added, 0 already present.\n"


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
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(blank)

    assert run("--data-dir", tmp_path, "import", blank) == (
        1,
        "",
        f"Error: cannot read {blank}: missing '/Contents'\n",
    )


def test_import_needs_at_least_one_file(tmp_path: Path) -> None:
    code, _, err = run("--data-dir", tmp_path, "import")
    assert code == 2  # noqa: PLR2004 - click's usage error
    assert "Missing argument 'FILES...'" in err
