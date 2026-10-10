import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from click.testing import CliRunner
from conftest import EUR_MONTHS, EUR_RATES

from inflation_station import clock
from inflation_station.cli import main

if TYPE_CHECKING:
    import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "jt_export.csv"
EUR_FUNDS = ("LU0260870158", "LU1883872332")
# Recorded EUR rates: 21 in May 2021, 22 in June, and 1 Jul.
RECORDED_RATES = 44


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def test_fetch_fx_stores_eur_rates_for_every_month_from_the_first_eur_purchase_to_today(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-fx") == (
        0,
        f"EUR: {RECORDED_RATES} rates added, 0 already present.\n",
        "",
    )


def test_refetching_requests_only_the_latest_stored_month_and_later(tmp_path: Path, recorded: dict[str, Path]) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-fx")
    # The fake fails on any URL it has no response for, so May and June must not be requested again.
    for month in EUR_MONTHS[:-1]:
        del recorded[EUR_RATES.format(month)]

    assert run("--data-dir", tmp_path, "fetch-fx") == (0, "EUR: 0 rates added, 1 already present.\n", "")


def test_a_month_fetched_before_it_ended_is_completed_on_the_next_fetch(
    tmp_path: Path, recorded: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    june = EUR_RATES.format("2021-06")
    full_june = recorded[june]
    recorded[june] = rates_up_to(full_june, date(2021, 6, 15), tmp_path / "june-so-far.json")
    monkeypatch.setattr(clock, "today", lambda: date(2021, 6, 15))
    run("--data-dir", tmp_path, "fetch-fx")
    monkeypatch.setattr(clock, "today", lambda: date(2021, 7, 1))
    recorded[june] = full_june
    del recorded[EUR_RATES.format("2021-05")]

    # June's 11 rates up to 15 Jun were stored already; the rest of June and 1 Jul are new.
    assert run("--data-dir", tmp_path, "fetch-fx") == (0, "EUR: 12 rates added, 11 already present.\n", "")


def rates_up_to(month: Path, last: date, copy: Path) -> Path:
    """A copy of the recorded `month` at `copy`, as ČNB would have answered on `last`."""
    response = json.loads(month.read_text(encoding="utf-8"))
    response["rates"] = [r for r in response["rates"] if date.fromisoformat(r["validFor"]) <= last]
    copy.write_text(json.dumps(response), encoding="utf-8")
    return copy


def test_only_currencies_that_purchases_are_priced_in_are_fetched(tmp_path: Path, recorded: dict[str, Path]) -> None:
    czk_only = tmp_path / "czk_only.csv"
    rows = EXPORT.read_text(encoding="utf-8").splitlines(keepends=True)
    czk_only.write_text("".join(r for r in rows if not any(isin in r for isin in EUR_FUNDS)), encoding="utf-8")
    run("--data-dir", tmp_path, "import", czk_only)
    recorded.clear()  # any request fails the test

    assert run("--data-dir", tmp_path, "fetch-fx") == (
        0,
        "Every Purchase is priced in CZK; no rates to fetch.\n",
        "",
    )


def test_fetch_fx_with_an_empty_database_fails_with_a_readable_message(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "fetch-fx") == (
        1,
        "",
        "Error: no Purchases to fetch rates for yet; import an export first: inflation-station import <csv>\n",
    )


def test_a_response_that_is_not_cnb_rates_fails_naming_its_url(tmp_path: Path, recorded: dict[str, Path]) -> None:
    june = EUR_RATES.format("2021-06")
    recorded[june] = FIXTURES / "cnb" / "README.md"
    run("--data-dir", tmp_path, "import", EXPORT)

    code, stdout, stderr = run("--data-dir", tmp_path, "fetch-fx")

    assert (code, stdout) == (1, "")
    assert stderr.startswith(f"Error: cannot read the ČNB rates {june}: ")
