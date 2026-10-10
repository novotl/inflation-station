import json
import socket
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from inflation_station import clock
from inflation_station.cli import main

EXPORT = Path(__file__).parent / "fixtures" / "jt_export.csv"
TODAY = date(2021, 7, 1)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "today", lambda: TODAY)


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

    assert run("--data-dir", tmp_path, "chart") == (0, f"Chart written to {tmp_path / 'chart.html'}\n", "")
    assert (tmp_path / "chart.html").read_text(encoding="utf-8").startswith("<!doctype html>")


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
