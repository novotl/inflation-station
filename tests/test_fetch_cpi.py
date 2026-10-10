from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import CPI_CSV, CSU
from test_chart import traces

from inflation_station.cli import main

EXPORT = Path(__file__).parent / "fixtures" / "jt_export.csv"
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
    recorded[CPI_CSV] = edited(recorded[CPI_CSV], '"květen 2021"', '"kveten 2021"', tmp_path / "typo.csv")

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CPI_CSV}: unknown month 'kveten 2021'\n",
    )


def test_a_missing_month_fails_rather_than_chaining_across_it(tmp_path: Path, recorded: dict[str, Path]) -> None:
    month_on_month = '"Přírůstek indexu spotřebitelských cen k předchozímu měsíci","Česko","září 2020"'
    recorded[CPI_CSV] = edited(
        recorded[CPI_CSV], month_on_month, month_on_month.replace("k před", "ke před"), tmp_path / "gap.csv"
    )

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CPI_CSV}: no month-on-month change for 2020-09\n",
    )


def test_a_response_that_is_not_the_csu_csv_fails_naming_its_url(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[CPI_CSV] = CSU / "README.md"

    code, stdout, stderr = run("--data-dir", tmp_path, "fetch-cpi")

    assert (code, stdout) == (1, "")
    assert stderr.startswith(f"Error: cannot read the ČSÚ CPI {CPI_CSV}: ")


def test_a_csv_without_month_on_month_changes_fails(tmp_path: Path, recorded: dict[str, Path]) -> None:
    header_only = tmp_path / "header-only.csv"
    header_only.write_bytes(recorded[CPI_CSV].read_bytes().splitlines(keepends=True)[0])
    recorded[CPI_CSV] = header_only

    assert run("--data-dir", tmp_path, "fetch-cpi") == (
        1,
        "",
        f"Error: cannot read the ČSÚ CPI {CPI_CSV}: no month-on-month changes\n",
    )


def without_months(csv: Path, months: tuple[str, ...], copy: Path) -> Path:
    """A copy of `csv` at `copy`, without the rows of `months`, e.g. `květen 2021`."""
    rows = csv.read_bytes().splitlines(keepends=True)
    copy.write_bytes(b"".join(r for r in rows if not any(f'"{m}"'.encode() in r for m in months)))
    return copy


def test_a_csv_starting_in_a_later_month_continues_from_the_stored_levels(
    tmp_path: Path, recorded: dict[str, Path]
) -> None:
    full = recorded[CPI_CSV]
    reference, data_dir = tmp_path / "reference", tmp_path / "data"
    for d in (reference, data_dir):
        run("--data-dir", d, "import", EXPORT)
    run("--data-dir", reference, "fetch-cpi")
    run("--data-dir", reference, "chart")
    recorded[CPI_CSV] = without_months(full, ("květen 2021",), tmp_path / "until-april.csv")
    run("--data-dir", data_dir, "fetch-cpi")
    # This one would chain from 100 in May 2020, where the stored levels have their own value.
    first_half_of_2020 = tuple(f"{m} 2020" for m in ("leden", "únor", "březen", "duben", "květen"))
    recorded[CPI_CSV] = without_months(full, first_half_of_2020, tmp_path / "from-june-2020.csv")

    assert run("--data-dir", data_dir, "fetch-cpi") == (0, "ČSÚ CPI: 1 months added, 12 already present.\n", "")
    run("--data-dir", data_dir, "chart")
    estimated = "Inflation hurdle (ČSÚ CPI, estimated)"
    assert traces(data_dir / "chart.html")[estimated]["y"] == pytest.approx(
        traces(reference / "chart.html")[estimated]["y"]
    )
