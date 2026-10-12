import json
import re
import socket
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from inflation_station import clock
from inflation_station.cli import main

EXPORT = Path(__file__).parent / "fixtures" / "jt_export.csv"
# ČSÚ's May 2021 change, 0.2 %, which by "today", 1 Jul 2021, also estimates June and July.
CSU_MAY = 1.002
# The fixture's Purchases, grown by an index rising `may` a month from May 2021: 104 000 CZK on 28 Apr and 100 000 CZK
# on 30 Apr (of 30 days), 13 000 CZK on 18 May (of 31), 5 000 CZK on 14 Jun and 13 000 CZK on 15 Jun (of 30).


def hurdle_on_1_jul(may: float) -> float:
    return (
        104000 * may ** (2 + 3 / 30)
        + 100000 * may ** (2 + 1 / 30)
        + 13000 * may ** (2 - 17 / 31)
        + 5000 * may ** (1 - 13 / 30)
        + 13000 * may ** (1 - 14 / 30)
    )


# On 1 Jul 2021: 79.90 FF World units at 1 463 CZK, 70 705 J&T Money units at 1.4089 CZK (carried forward from
# 30 Jun), and at ČNB's 25.505 CZK per EUR, 11.15 Franklin units at 37.86 EUR and 12.07 Amundi units at 16.15 EUR.
FF_WORLD, JT_MONEY = 79.90 * 1463, 70705 * 1.4089
FRANKLIN, AMUNDI = 11.15 * 37.86 * 25.505, 12.07 * 16.15 * 25.505


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def page(data_dir: Path) -> dict:
    """The data the written chart page is drawn from, read back from the JSON in its HTML."""
    html = (data_dir / "chart.html").read_text(encoding="utf-8")
    return json.loads(html.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0])


def by_name(traces: list[dict]) -> dict[str, dict]:
    return {trace["name"]: trace for trace in traces}


def overall(data_dir: Path) -> dict[str, dict]:
    """The portfolio chart's traces by name: its value, the amount invested and the hurdles."""
    return by_name(page(data_dir)["portfolio"]["chart"])


def composition(data_dir: Path) -> dict[str, dict]:
    """The traces by name of the portfolio chart with its value split into stacked fund values."""
    return by_name(page(data_dir)["portfolio"]["composition"])


def fetch_everything(data_dir: Path) -> None:
    run("--data-dir", data_dir, "import", EXPORT)
    for command in ("fetch-prices", "fetch-fx", "fetch-cpi"):
        run("--data-dir", data_dir, command)


def hover(line: dict, n: int) -> str:
    """The hover text of a line's nth point, as plotly would fill in its template."""
    text = line["hovertemplate"].replace("%{y:,.2f}", f"{line['y'][n]:,.2f}")
    for m, value in enumerate(line["customdata"][n]):
        if isinstance(value, float):
            text = text.replace(f"%{{customdata[{m}]:,.2f}}", f"{value:,.2f}")
        text = text.replace(f"%{{customdata[{m}]}}", str(value))
    return text.removesuffix("<extra></extra>")


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
    assert set(overall(tmp_path)) == set(composition(tmp_path)) == {"Amount invested"}
    assert page(tmp_path)["portfolio"]["value"] is None
    assert page(tmp_path)["portfolio"]["relative"] == []


def test_after_fetching_prices_the_chart_has_a_portfolio_line_and_stacks_each_czk_funds_value(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    lines = overall(tmp_path)
    assert set(lines) == {"Amount invested", "Portfolio value"}
    assert lines["Portfolio value"]["y"][-1] == pytest.approx(FF_WORLD + JT_MONEY)
    assert len(lines["Portfolio value"]["y"]) == len(lines["Amount invested"]["y"])
    # The fund values stack up to the portfolio value, largest fund on top.
    stacked = page(tmp_path)["portfolio"]["composition"]
    assert [t["name"] for t in stacked] == ["J&T MONEY A CZK OPF", "FF - World Fund A-ACC-CZK", "Amount invested"]
    assert [t.get("stackgroup") for t in stacked] == ["value", "value", None]
    assert stacked[0]["y"][-1] == pytest.approx(JT_MONEY)
    assert stacked[1]["y"][-1] == pytest.approx(FF_WORLD)


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
    lines = composition(tmp_path)
    assert set(lines) == {
        "Amount invested",
        "J&T MONEY A CZK OPF",
        "FF - World Fund A-ACC-CZK",
        "FTIF-Franklin Technology Fund-A(acc)EUR",
        "AMUNDI FUNDS US PIONEER FUND - A EUR (C)",
    }
    assert lines["FTIF-Franklin Technology Fund-A(acc)EUR"]["y"][-1] == pytest.approx(FRANKLIN)
    assert lines["AMUNDI FUNDS US PIONEER FUND - A EUR (C)"]["y"][-1] == pytest.approx(AMUNDI)
    assert overall(tmp_path)["Portfolio value"]["y"][-1] == pytest.approx(FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI)


def test_amount_invested_is_a_step_line_from_the_first_trade_date_to_today(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "chart")

    invested = overall(tmp_path)["Amount invested"]
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


def test_the_page_is_one_self_contained_file(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    html = (tmp_path / "chart.html").read_text(encoding="utf-8")
    # plotly.js, the page's CSS and JS are inlined, and nothing is loaded from elsewhere, fonts included.
    assert 'src="http' not in html
    assert "<link" not in html
    assert not {"{{STYLE}}", "{{PLOTLY}}", "{{SCRIPT}}"} & set(re.findall(r"\{\{[A-Z]+\}\}", html))  # all filled in
    assert len(page(tmp_path)["funds"]) == 4  # noqa: PLR2004 - the fixture's funds


def test_chart_with_an_empty_database_fails_with_a_readable_message(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "chart") == (
        1,
        "",
        "Error: no Purchases or Deposits to chart yet; import first: inflation-station import <file>...\n",
    )
    assert list(tmp_path.iterdir()) == []  # neither a chart nor a database was created


def test_after_fetching_cpi_the_chart_has_a_solid_hurdle_line_and_a_dotted_estimated_tail(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-cpi")
    run("--data-dir", tmp_path, "chart")

    lines = overall(tmp_path)
    published, estimated = lines["Inflation hurdle (ČSÚ CPI)"], lines["Inflation hurdle (ČSÚ CPI, estimated)"]
    assert published["line"]["dash"] == "solid"
    assert estimated["line"]["dash"] == "dot"
    # May 2021 is the last month published by "today", 1 Jul 2021, so the index is published only up to 1 May; the
    # estimated tail starts there, so the two lines meet.
    assert (published["x"][0], published["x"][-1]) == ("2021-04-28", "2021-05-01")
    assert (estimated["x"][0], estimated["x"][-1]) == ("2021-05-01", "2021-07-01")
    # May's level is 0.2 % above April's, placed on 1 May, with constant daily growth over April's 30 days.
    assert published["y"][-1] == pytest.approx(104000 * CSU_MAY ** (3 / 30) + 100000 * CSU_MAY ** (1 / 30))
    assert estimated["y"][-1] == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    # The relative charts measure against ČSÚ CPI, shading its estimated part: from the first day not published.
    assert (page(tmp_path)["benchmark"], page(tmp_path)["estimatedFrom"]) == ("ČSÚ CPI", "2021-05-02")


def test_after_fetching_cpi_the_chart_has_a_dashed_eurostat_hurdle_line_and_a_dotted_estimated_tail(
    tmp_path: Path,
) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-cpi")
    run("--data-dir", tmp_path, "chart")

    lines = overall(tmp_path)
    published, estimated = (
        lines["Inflation hurdle (Eurostat HICP)"],
        lines["Inflation hurdle (Eurostat HICP, estimated)"],
    )
    assert published["line"]["dash"] == "dash"
    assert estimated["line"]["dash"] == "dot"
    # Eurostat too had published May 2021 last by "today", 1 Jul 2021.
    assert (published["x"][0], published["x"][-1]) == ("2021-04-28", "2021-05-01")
    assert (estimated["x"][0], estimated["x"][-1]) == ("2021-05-01", "2021-07-01")
    # The index levels of April and May 2021; as for ČSÚ, with May's change repeated for June and July.
    may = 114.14 / 114.02
    assert published["y"][-1] == pytest.approx(104000 * may ** (3 / 30) + 100000 * may ** (1 / 30))
    assert estimated["y"][-1] == pytest.approx(hurdle_on_1_jul(may))


def test_each_line_has_the_role_that_colours_it_the_same_on_every_chart(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    assert {name: line.get("meta") for name, line in overall(tmp_path).items()} == {
        "Portfolio value": "value",
        "Amount invested": "invested",
        "Inflation hurdle (ČSÚ CPI)": "inflation",
        "Inflation hurdle (ČSÚ CPI, estimated)": "inflation",
        "Inflation hurdle (Eurostat HICP)": "inflation",
        "Inflation hurdle (Eurostat HICP, estimated)": "inflation",
    }
    franklin = by_name(data["funds"][2]["chart"])
    assert (franklin["Value"]["meta"], franklin["Amount invested"]["meta"]) == ("value", "invested")
    # Stacked fund values take the colourway, one colour per fund.
    assert "meta" not in composition(tmp_path)["FF - World Fund A-ACC-CZK"]
    # The relative lines take the colour of what they're measured against.
    assert [(t["name"], t["meta"]) for t in data["portfolio"]["relative"]] == [
        ("real", "inflation"),
        ("nominal", "invested"),
    ]


def test_the_relative_lines_are_the_value_above_the_cpi_hurdle_and_the_amount_invested(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    value = FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI
    real, nominal = data["portfolio"]["relative"]
    assert real["y"][-1] == pytest.approx(value / hurdle_on_1_jul(CSU_MAY) - 1)
    assert nominal["y"][-1] == pytest.approx(value / 235000 - 1)
    assert real["hovertemplate"] == nominal["hovertemplate"] == "%{y:+.1%}"
    # Franklin's: two Purchases of 5 000 CZK, fees included, on 18 May and 14 Jun 2021.
    franklin_real, franklin_nominal = data["funds"][2]["relative"]
    franklin_hurdle = 5000 * CSU_MAY ** (2 - 17 / 31) + 5000 * CSU_MAY ** (1 - 13 / 30)
    assert franklin_real["y"][-1] == pytest.approx(FRANKLIN / franklin_hurdle - 1)
    assert franklin_nominal["y"][-1] == pytest.approx(FRANKLIN / 10000 - 1)
    # Before Franklin's first Purchase there is nothing to measure.
    assert franklin_nominal["y"][0] is None


def test_without_cpi_the_relative_chart_has_only_the_nominal_line(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    assert (data["benchmark"], data["estimatedFrom"]) == (None, None)
    assert [t["name"] for t in data["portfolio"]["relative"]] == ["nominal"]
    assert data["portfolio"]["hurdles"] == []


def test_the_page_has_the_portfolios_figures_on_the_last_day(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    portfolio = page(tmp_path)["portfolio"]
    assert page(tmp_path)["asOf"] == "2021-07-01"
    assert portfolio["value"] == pytest.approx(FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI)
    assert portfolio["invested"] == 235000  # noqa: PLR2004 - the fixture's Purchases, fees included
    assert portfolio["benchmarkHurdle"] == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    assert [h["name"] for h in portfolio["hurdles"]] == ["ČSÚ CPI", "Eurostat HICP"]
    assert portfolio["hurdles"][1]["value"] == pytest.approx(hurdle_on_1_jul(114.14 / 114.02))


def test_chart_with_fresh_data_warns_of_nothing(tmp_path: Path) -> None:
    fetch_everything(tmp_path)

    assert run("--data-dir", tmp_path, "chart")[::2] == (0, "")
    assert page(tmp_path)["warnings"] == []


def test_chart_names_each_out_of_date_series_and_its_last_date_but_is_still_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch_everything(tmp_path)
    monkeypatch.setattr(clock, "today", lambda: date(2021, 8, 2))

    exit_code, stdout, stderr = run("--data-dir", tmp_path, "chart")

    assert (exit_code, stdout) == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    assert stderr == (
        "Out of date: J&T MONEY A CZK OPF (CZ0008473808) prices end on 2021-06-30; run inflation-station fetch-prices\n"
        "Out of date: FTIF-Franklin Technology Fund-A(acc)EUR (LU0260870158) prices end on 2021-07-01; "
        "run inflation-station fetch-prices\n"
        "Out of date: FF - World Fund A-ACC-CZK (LU1756523376) prices end on 2021-07-01; "
        "run inflation-station fetch-prices\n"
        "Out of date: AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332) prices end on 2021-07-01; "
        "run inflation-station fetch-prices\n"
        "Out of date: EUR rates end on 2021-07-01; run inflation-station fetch-fx\n"
        "Out of date: ČSÚ CPI ends with 2021-05; run inflation-station fetch-cpi\n"
        "Out of date: Eurostat HICP ends with 2021-05; run inflation-station fetch-cpi\n"
    )
    # The page shows the same warnings.
    assert page(tmp_path)["warnings"] == [line.removeprefix("Out of date: ") for line in stderr.splitlines()]
    assert overall(tmp_path)["Amount invested"]["x"][-1] == "2021-08-02"


def test_chart_warns_only_of_the_series_that_are_out_of_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_everything(tmp_path)
    # Five business days after J&T Money's last price on Wed 30 Jun, but only four after the others' on Thu 1 Jul.
    monkeypatch.setattr(clock, "today", lambda: date(2021, 7, 8))

    assert run("--data-dir", tmp_path, "chart")[::2] == (
        0,
        (
            "Out of date: J&T MONEY A CZK OPF (CZ0008473808) prices end on 2021-06-30; "
            "run inflation-station fetch-prices\n"
        ),
    )


def test_each_fund_hovers_with_its_units_and_its_value_in_its_own_currency(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    lines = composition(tmp_path)
    assert hover(lines["FTIF-Franklin Technology Fund-A(acc)EUR"], -1) == (
        f"{FRANKLIN:,.2f} CZK ({11.15 * 37.86:,.2f} EUR) · 11.15 units"
    )
    # CZK funds have no bracketed amount; units are shown as stored, trailing zeros trimmed.
    assert hover(lines["FF - World Fund A-ACC-CZK"], -1) == f"{FF_WORLD:,.2f} CZK · 79.9 units"
    assert hover(lines["J&T MONEY A CZK OPF"], -1) == f"{JT_MONEY:,.2f} CZK · 70,705 units"


def test_portfolio_invested_and_hurdle_lines_hover_with_their_czk_value_only(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    lines = overall(tmp_path)
    for name in ("Portfolio value", "Amount invested", "Inflation hurdle (ČSÚ CPI)"):
        assert lines[name]["hovertemplate"] == "%{y:,.2f} CZK"
        assert "customdata" not in lines[name]


def test_funds_come_largest_value_first_with_their_name_isin_and_currency(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    # On 1 Jul 2021: FF World 116 893 CZK, J&T Money 99 616 CZK, Franklin 10 767 CZK, Amundi 4 972 CZK.
    assert [(f["name"], f["isin"], f["pricedIn"]) for f in page(tmp_path)["funds"]] == [
        ("FF - World Fund A-ACC-CZK", "LU1756523376", "CZK"),
        ("J&T MONEY A CZK OPF", "CZ0008473808", "CZK"),
        ("FTIF-Franklin Technology Fund-A(acc)EUR", "LU0260870158", "EUR"),
        ("AMUNDI FUNDS US PIONEER FUND - A EUR (C)", "LU1883872332", "EUR"),
    ]


def test_each_fund_has_its_figures_on_the_last_day(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    ff_world, _, franklin, _ = page(tmp_path)["funds"]
    assert franklin["value"] == pytest.approx(FRANKLIN)
    assert franklin["currencyValue"] == f"{11.15 * 37.86:,.2f} EUR"
    assert (franklin["invested"], franklin["units"], franklin["notValued"]) == (10000, "11.15", None)
    assert franklin["benchmarkHurdle"] == pytest.approx(
        5000 * CSU_MAY ** (2 - 17 / 31) + 5000 * CSU_MAY ** (1 - 13 / 30)
    )
    # Valued in CZK: no second currency.
    assert (ff_world["currencyValue"], ff_world["units"]) == (None, "79.9")


def test_a_funds_chart_has_its_value_amount_invested_and_hurdles_in_czk(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    lines = by_name(page(tmp_path)["funds"][2]["chart"])
    assert set(lines) == {
        "Value",
        "Amount invested",
        "Inflation hurdle (ČSÚ CPI)",
        "Inflation hurdle (ČSÚ CPI, estimated)",
        "Inflation hurdle (Eurostat HICP)",
        "Inflation hurdle (Eurostat HICP, estimated)",
    }
    # Hovers as the fund's line on the portfolio chart does.
    assert hover(lines["Value"], -1) == f"{FRANKLIN:,.2f} CZK ({11.15 * 37.86:,.2f} EUR) · 11.15 units"
    # Two Purchases of 5 000 CZK, fees included: on 18 May and 14 Jun 2021.
    invested = lines["Amount invested"]
    assert (invested["y"][0], invested["y"][-1], invested["line"]["shape"]) == (0, 10000, "hv")
    assert invested["hovertemplate"] == "%{y:,.2f} CZK"
    # Only Franklin's Purchases grow, at May's 0.2 %, carried forward.
    estimated = lines["Inflation hurdle (ČSÚ CPI, estimated)"]
    assert estimated["y"][-1] == pytest.approx(5000 * CSU_MAY ** (2 - 17 / 31) + 5000 * CSU_MAY ** (1 - 13 / 30))
    assert estimated["line"]["dash"] == "dot"
    assert lines["Inflation hurdle (Eurostat HICP)"]["line"]["dash"] == "dash"


def test_funds_that_cannot_be_valued_come_last_saying_why(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "fetch-cpi")
    run("--data-dir", tmp_path, "chart")

    funds = page(tmp_path)["funds"]
    # The EUR funds have no rates, so only the CZK funds are valued.
    assert [f["isin"] for f in funds] == ["LU1756523376", "CZ0008473808", "LU0260870158", "LU1883872332"]
    franklin = funds[2]
    assert (franklin["notValued"], franklin["value"], franklin["relative"]) == ("no EUR rates stored", None, [])
    assert set(by_name(franklin["chart"])) == {
        "Amount invested",
        "Inflation hurdle (ČSÚ CPI)",
        "Inflation hurdle (ČSÚ CPI, estimated)",
        "Inflation hurdle (Eurostat HICP)",
        "Inflation hurdle (Eurostat HICP, estimated)",
    }
    # With no value line, amount invested carries the units held.
    assert hover(by_name(franklin["chart"])["Amount invested"], -1) == "10,000.00 CZK · 11.15 units"
    assert funds[0]["notValued"] is None


def test_without_prices_a_fund_is_priced_in_the_currency_it_was_bought_in(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "chart")

    amundi = next(f for f in page(tmp_path)["funds"] if f["isin"] == "LU1883872332")
    assert (amundi["pricedIn"], amundi["notValued"]) == ("EUR", "no prices stored")
