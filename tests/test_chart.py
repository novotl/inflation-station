import json
import socket
from pathlib import Path

import pytest
from click.testing import CliRunner

from inflation_station.cli import main

EXPORT = Path(__file__).parent / "fixtures" / "jt_export.csv"


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def traces(chart: Path) -> dict[str, dict]:
    """The chart's plotly traces by name, read back from the JSON in the written HTML."""
    html = chart.read_text(encoding="utf-8")
    after_div_id = html.split("Plotly.newPlot(", 1)[1].split(",", 1)[1].lstrip()
    data, _ = json.JSONDecoder().raw_decode(after_div_id)
    return {trace["name"]: trace for trace in data}


def test_chart_writes_an_html_file_in_the_data_directory(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "chart")[:2] == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    assert (tmp_path / "chart.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_chart_before_fetching_prices_names_the_funds_it_could_not_value(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "chart")[2] == (
        "Not valued (no prices stored; run inflation-station fetch-prices): J&T MONEY A CZK OPF (CZ0008473808), "
        "FTIF-Franklin Technology Fund-A(acc)EUR (LU0260870158), FF - World Fund A-ACC-CZK (LU1756523376), "
        "AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332)\n"
    )
    assert set(traces(tmp_path / "chart.html")) == {"Amount invested"}


def test_after_fetching_prices_the_chart_has_a_line_per_czk_fund_and_a_portfolio_line(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    lines = traces(tmp_path / "chart.html")
    assert set(lines) == {"Amount invested", "Portfolio value", "J&T MONEY A CZK OPF", "FF - World Fund A-ACC-CZK"}
    # On 1 Jul 2021: 79.90 FF World units at 1 463 CZK, and 70 705 J&T Money units at 1.4089 CZK, carried
    # forward from 30 Jun.
    ff_world, jt_money = 79.90 * 1463, 70705 * 1.4089
    assert lines["FF - World Fund A-ACC-CZK"]["y"][-1] == pytest.approx(ff_world)
    assert lines["J&T MONEY A CZK OPF"]["y"][-1] == pytest.approx(jt_money)
    assert lines["Portfolio value"]["y"][-1] == pytest.approx(ff_world + jt_money)
    assert len(lines["Portfolio value"]["y"]) == len(lines["Amount invested"]["y"])


def test_chart_before_fetching_rates_names_the_eur_funds_it_could_not_value(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")

    assert run("--data-dir", tmp_path, "chart")[2] == (
        "Not valued (no EUR rates stored; run inflation-station fetch-fx): FTIF-Franklin Technology Fund-A(acc)EUR "
        "(LU0260870158), AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332)\n"
    )


def test_after_fetching_prices_and_rates_the_chart_values_every_fund_in_czk(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "fetch-fx")

    assert run("--data-dir", tmp_path, "chart")[::2] == (0, "")  # nothing left out
    lines = traces(tmp_path / "chart.html")
    assert set(lines) == {
        "Amount invested",
        "Portfolio value",
        "J&T MONEY A CZK OPF",
        "FF - World Fund A-ACC-CZK",
        "FTIF-Franklin Technology Fund-A(acc)EUR",
        "AMUNDI FUNDS US PIONEER FUND - A EUR (C)",
    }
    # On 1 Jul 2021, at ČNB's 25.505 CZK per EUR: 11.15 Franklin units at 37.86 EUR, 12.07 Amundi units at 16.15 EUR.
    franklin, amundi = 11.15 * 37.86 * 25.505, 12.07 * 16.15 * 25.505
    assert lines["FTIF-Franklin Technology Fund-A(acc)EUR"]["y"][-1] == pytest.approx(franklin)
    assert lines["AMUNDI FUNDS US PIONEER FUND - A EUR (C)"]["y"][-1] == pytest.approx(amundi)
    czk_funds = 79.90 * 1463 + 70705 * 1.4089
    assert lines["Portfolio value"]["y"][-1] == pytest.approx(czk_funds + franklin + amundi)


def test_amount_invested_is_a_step_line_from_the_first_trade_date_to_today(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "chart")

    invested = traces(tmp_path / "chart.html")["Amount invested"]
    assert invested["line"]["shape"] == "hv"
    # The fixture's first trade is 104 000 CZK on 28.04.2021; its seven Purchases total 235 000 CZK.
    assert (invested["x"][0], invested["y"][0]) == ("2021-04-28", 104000)
    assert (invested["x"][-1], invested["y"][-1]) == ("2021-07-01", 235000)
    days_28_apr_to_1_jul = 65
    assert len(invested["x"]) == len(invested["y"]) == days_28_apr_to_1_jul  # one point per day


def test_chart_makes_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    def no_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("chart opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    assert run("--data-dir", tmp_path, "chart")[0] == 0
    assert 'src="http' not in (tmp_path / "chart.html").read_text(encoding="utf-8")  # plotly.js is inlined


def test_chart_with_an_empty_database_fails_with_a_readable_message(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "chart") == (
        1,
        "",
        "Error: no Purchases to chart yet; import an export first: inflation-station import <csv>\n",
    )
    assert list(tmp_path.iterdir()) == []  # neither a chart nor a database was created
