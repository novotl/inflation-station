from pathlib import Path

from click.testing import CliRunner
from conftest import CSU_CPI

from inflation_station.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
# The month-on-month changes of January 2020 to May 2021, chained from December 2019.
RECORDED_MONTHS = 18


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def test_fetch_cpi_stores_a_level_for_every_month_and_the_one_before_the_first(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        0,
        f"ČSÚ CPI: {RECORDED_MONTHS} months added, 0 already present.\n",
        "",
    )


def test_refetching_adds_no_duplicates(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "fetch-cpi")

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        0,
        f"ČSÚ CPI: 0 months added, {RECORDED_MONTHS} already present.\n",
        "",
    )


def edited(csv: Path, old: str, new: str, copy: Path) -> Path:
    """A copy of `csv` at `copy`, with `old` replaced by `new`."""
    copy.write_bytes(csv.read_bytes().replace(old.encode(), new.encode()))
    return copy


def test_an_unknown_month_name_fails_naming_it(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[CSU_CPI] = edited(recorded[CSU_CPI], '"květen 2021"', '"kveten 2021"', tmp_path / "typo.csv")

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CSU_CPI}: unknown month 'kveten 2021'\n",
    )


def test_a_missing_month_fails_rather_than_chaining_across_it(tmp_path: Path, recorded: dict[str, Path]) -> None:
    month_on_month = '"Přírůstek indexu spotřebitelských cen k předchozímu měsíci","Česko","září 2020"'
    recorded[CSU_CPI] = edited(
        recorded[CSU_CPI], month_on_month, month_on_month.replace("k před", "ke před"), tmp_path / "gap.csv"
    )

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CSU_CPI}: no month-on-month change for 2020-09\n",
    )


def test_a_response_that_is_not_the_csu_csv_fails_naming_its_url(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[CSU_CPI] = FIXTURES / "csu" / "README.md"

    code, stdout, stderr = run("--data-dir", tmp_path, "fetch-cpi")

    assert (code, stdout) == (1, "")
    assert stderr.startswith(f"Error: cannot read the ČSÚ CPI {CSU_CPI}: ")


def test_a_csv_without_month_on_month_changes_fails(tmp_path: Path, recorded: dict[str, Path]) -> None:
    header_only = tmp_path / "header-only.csv"
    header_only.write_bytes(recorded[CSU_CPI].read_bytes().splitlines(keepends=True)[0])
    recorded[CSU_CPI] = header_only

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CSU_CPI}: no month-on-month changes\n",
    )
