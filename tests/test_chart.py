import json
import re
import socket
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from inflation_station import clock
from inflation_station.chart import write_chart
from inflation_station.cli import main
from inflation_station.domain import Deposit, Fund, Platform, Portfolio, Purchase, Rows
from inflation_station.fund_price import FundPrice
from inflation_station.store import Store
from inflation_station.valuation import timeline

EXPORT = Path(__file__).parent / "fixtures" / "jt_export.csv"
# ČSÚ's May 2021 change, 0.2 %, which by "today", 1 Jul 2021, also estimates June and July.
CSU_MAY = 1.002
# The fixture's Deposits, grown by an index rising `may` a month from May 2021: 104 000 CZK on 3 May, 100 000 CZK on
# 4 May and 13 000 CZK on 21 May (of 31 days), 5 000 CZK on 17 Jun and 13 000 CZK on 18 Jun (of 30).


def hurdle_on_1_jul(may: float) -> float:
    return (
        104000 * may ** (2 - 2 / 31)
        + 100000 * may ** (2 - 3 / 31)
        + 13000 * may ** (2 - 20 / 31)
        + 5000 * may ** (1 - 16 / 30)
        + 13000 * may ** (1 - 17 / 30)
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


def whole_portfolio_chart(data_dir: Path) -> dict[str, dict]:
    """The Whole Portfolio chart's traces by name: its value, the amount invested and the hurdles."""
    return by_name(page(data_dir)["wholePortfolio"]["chart"])


def composition(data_dir: Path) -> dict[str, dict]:
    """The traces by name of the Whole Portfolio chart with its value split into stacked Portfolio values."""
    return by_name(page(data_dir)["wholePortfolio"]["composition"])


def fetch_everything(data_dir: Path) -> None:
    run("--data-dir", data_dir, "import", EXPORT)
    for command in ("fetch-prices", "fetch-fx", "fetch-cpi"):
        run("--data-dir", data_dir, command)


def not_valued(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("Not valued")]


def warned_of_other_than_negative_cash(stderr: str) -> str:
    """`stderr` without its Negative Cash warnings: the fixture's J&T Deposits came a few days after their trades."""
    return "".join(line for line in stderr.splitlines(keepends=True) if not line.startswith("Negative Cash"))


def test_chart_writes_an_html_file_in_the_data_directory(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "chart")[:2] == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    assert (tmp_path / "chart.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_chart_before_fetching_prices_names_the_funds_it_could_not_value(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert not_valued(run("--data-dir", tmp_path, "chart")[2]) == [
        (
            "Not valued (no prices stored; run inflation-station fetch-prices): J&T MONEY A CZK OPF (CZ0008473808), "
            "FTIF-Franklin Technology Fund-A(acc)EUR (LU0260870158), FF - World Fund A-ACC-CZK (LU1756523376), "
            "AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332)"
        ),
        # J&T's EUR Cash is spent the day it is converted, but without rates even that isn't known.
        "Not valued (no EUR rates stored; run inflation-station fetch-fx): EUR Cash",
    ]
    # Only the CZK Cash is valued: by 1 Jul, every Deposit has been spent.
    assert set(whole_portfolio_chart(tmp_path)) == {"Whole Portfolio value", "Amount invested"}
    assert set(composition(tmp_path)) == {
        "J&T Banka · J&T MONEY A CZK OPF",
        "J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR",
        "J&T Banka · FF - World Fund A-ACC-CZK",
        "J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C)",
        "Amount invested",
    }
    assert page(tmp_path)["wholePortfolio"]["value"] == 0


def test_after_fetching_prices_the_chart_has_a_whole_portfolio_line_and_stacks_each_portfolios_value(
    tmp_path: Path,
) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    lines = whole_portfolio_chart(tmp_path)
    assert set(lines) == {"Amount invested", "Whole Portfolio value"}
    assert lines["Whole Portfolio value"]["y"][-1] == pytest.approx(FF_WORLD + JT_MONEY)
    assert len(lines["Whole Portfolio value"]["y"]) == len(lines["Amount invested"]["y"])
    # The Portfolio values stack up to the Whole Portfolio value, largest on top. The EUR funds' Portfolios are
    # valued by their CZK Cash only, all spent by 1 Jul.
    stacked = page(tmp_path)["wholePortfolio"]["composition"]
    assert [t["name"] for t in stacked] == [
        "J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C)",
        "J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR",
        "J&T Banka · J&T MONEY A CZK OPF",
        "J&T Banka · FF - World Fund A-ACC-CZK",
        "Amount invested",
    ]
    assert [t.get("stackgroup") for t in stacked] == ["value", "value", "value", "value", None]
    assert [t["y"][-1] for t in stacked[:4]] == pytest.approx([0, 0, JT_MONEY, FF_WORLD])


def test_chart_before_fetching_rates_names_the_eur_funds_it_could_not_value(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")

    assert not_valued(run("--data-dir", tmp_path, "chart")[2]) == [
        (
            "Not valued (no EUR rates stored; run inflation-station fetch-fx): FTIF-Franklin Technology Fund-A(acc)EUR "
            "(LU0260870158), AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332), EUR Cash"
        )
    ]


def test_after_fetching_prices_and_rates_the_chart_values_every_fund_in_czk(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "fetch-fx")

    assert not_valued(run("--data-dir", tmp_path, "chart")[2]) == []  # nothing left out
    lines = composition(tmp_path)
    assert lines["J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR"]["y"][-1] == pytest.approx(FRANKLIN)
    assert lines["J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C)"]["y"][-1] == pytest.approx(AMUNDI)
    assert whole_portfolio_chart(tmp_path)["Whole Portfolio value"]["y"][-1] == pytest.approx(
        FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI
    )


def test_amount_invested_is_a_step_line_of_the_deposits_from_the_first_row_to_today(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "chart")

    invested = whole_portfolio_chart(tmp_path)["Amount invested"]
    assert invested["line"]["shape"] == "hv"
    # The fixture's first row is a trade on 28.04.2021, its first Deposit 104 000 CZK on 03.05.2021; its seven
    # Deposits, each paying for a Purchase and its Fee, total 235 000 CZK.
    by_day = dict(zip(invested["x"], invested["y"], strict=True))
    assert (invested["x"][0], invested["y"][0]) == ("2021-04-28", 0)
    assert (by_day["2021-05-02"], by_day["2021-05-03"]) == (0, 104000)
    assert (invested["x"][-1], invested["y"][-1]) == ("2021-07-01", 235000)
    days_28_apr_to_1_jul = 65
    assert len(invested["x"]) == len(invested["y"]) == days_28_apr_to_1_jul  # one point per day


def negative_cash(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("Negative Cash")]


def test_chart_warns_of_each_portfolios_negative_cash_by_currency_naming_its_days_but_is_still_written(
    tmp_path: Path,
) -> None:
    fetch_everything(tmp_path)

    exit_code, stdout, stderr = run("--data-dir", tmp_path, "chart")

    assert (exit_code, stdout) == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    # J&T took each Deposit a few days after the trade it paid for, so until then the Portfolio's Cash was negative.
    assert negative_cash(stderr) == [
        "Negative Cash (CZK): J&T Banka · J&T MONEY A CZK OPF on 2021-04-30 to 2021-05-03",
        (
            "Negative Cash (CZK): J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR on 2021-05-18 to 2021-05-20, "
            "2021-06-14 to 2021-06-16"
        ),
        (
            "Negative Cash (CZK): J&T Banka · FF - World Fund A-ACC-CZK on 2021-04-28 to 2021-05-02, 2021-05-18 to "
            "2021-05-20, 2021-06-15 to 2021-06-17"
        ),
        "Negative Cash (CZK): J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C) on 2021-06-15 to 2021-06-17",
    ]


def test_negative_cash_for_a_single_day_names_that_day(tmp_path: Path) -> None:
    portfolio = Portfolio(Platform.JT, "900000001", "900000001")
    rows = Rows(
        deposits=[Deposit(portfolio, "1", date(2021, 6, 14), Decimal(20), "CZK")], purchases=[ff_world(units=2)]
    )
    Store(tmp_path).add_rows(rows)

    assert negative_cash(run("--data-dir", tmp_path, "chart")[2]) == [
        "Negative Cash (CZK): J&T Banka · 900000001 on 2021-06-13"
    ]


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

    lines = whole_portfolio_chart(tmp_path)
    published, estimated = lines["Inflation hurdle (ČSÚ CPI)"], lines["Inflation hurdle (ČSÚ CPI, estimated)"]
    assert published["line"]["dash"] == "solid"
    assert estimated["line"]["dash"] == "dot"
    # May 2021 is the last month published by "today", 1 Jul 2021, so the index is published only up to 1 May; the
    # estimated tail starts there, so the two lines meet.
    assert (published["x"][0], published["x"][-1]) == ("2021-04-28", "2021-05-01")
    assert (estimated["x"][0], estimated["x"][-1]) == ("2021-05-01", "2021-07-01")
    # Nothing is deposited before 3 May.
    assert set(published["y"]) == {0}
    assert estimated["y"][-1] == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    # The relative charts measure against ČSÚ CPI, shading its estimated part: from the first day not published.
    assert (page(tmp_path)["benchmark"], page(tmp_path)["estimatedFrom"]) == ("ČSÚ CPI", "2021-05-02")


def test_after_fetching_cpi_the_chart_has_a_dashed_eurostat_hurdle_line_and_a_dotted_estimated_tail(
    tmp_path: Path,
) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-cpi")
    run("--data-dir", tmp_path, "chart")

    lines = whole_portfolio_chart(tmp_path)
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
    assert estimated["y"][-1] == pytest.approx(hurdle_on_1_jul(may))


def test_each_line_has_the_role_that_colours_it_the_same_on_every_chart(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    assert {name: line.get("meta") for name, line in whole_portfolio_chart(tmp_path).items()} == {
        "Whole Portfolio value": "value",
        "Amount invested": "invested",
        "Inflation hurdle (ČSÚ CPI)": "inflation",
        "Inflation hurdle (ČSÚ CPI, estimated)": "inflation",
        "Inflation hurdle (Eurostat HICP)": "inflation",
        "Inflation hurdle (Eurostat HICP, estimated)": "inflation",
    }
    assert by_name(data["platformTotals"][0]["chart"])["Value"]["meta"] == "value"
    # Stacked Portfolio values take the colourway, one colour per Portfolio.
    assert "meta" not in composition(tmp_path)["J&T Banka · FF - World Fund A-ACC-CZK"]
    # The relative lines take the colour of what they're measured against.
    assert [(t["name"], t["meta"]) for t in data["wholePortfolio"]["relative"]] == [
        ("real", "inflation"),
        ("nominal", "invested"),
    ]


def test_the_relative_lines_are_the_value_above_the_cpi_hurdle_and_the_amount_invested(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    value = FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI
    real, nominal = data["wholePortfolio"]["relative"]
    assert real["y"][-1] == pytest.approx(value / hurdle_on_1_jul(CSU_MAY) - 1)
    assert nominal["y"][-1] == pytest.approx(value / 235000 - 1)
    assert real["hovertemplate"] == nominal["hovertemplate"] == "%{y:+.1%}"
    # Franklin's Portfolio: two Deposits of 5 000 CZK, on 21 May and 17 Jun 2021, each spent on a Purchase and its Fee.
    (franklin,) = (p for p in data["portfolios"] if p["name"] == "J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR")
    franklin_real, franklin_nominal = franklin["relative"]
    franklin_hurdle = 5000 * CSU_MAY ** (2 - 20 / 31) + 5000 * CSU_MAY ** (1 - 16 / 30)
    assert franklin_real["y"][-1] == pytest.approx(FRANKLIN / franklin_hurdle - 1)
    assert franklin_nominal["y"][-1] == pytest.approx(FRANKLIN / 10000 - 1)
    # Before its first Deposit there is nothing to measure.
    assert franklin_nominal["y"][0] is None


def test_without_cpi_the_relative_chart_has_only_the_nominal_line(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    data = page(tmp_path)
    assert (data["benchmark"], data["estimatedFrom"]) == (None, None)
    assert [t["name"] for t in data["wholePortfolio"]["relative"]] == ["nominal"]
    assert data["wholePortfolio"]["hurdles"] == []


def test_the_page_has_the_whole_portfolios_figures_on_the_last_day(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    whole_portfolio = page(tmp_path)["wholePortfolio"]
    assert page(tmp_path)["asOf"] == "2021-07-01"
    assert whole_portfolio["value"] == pytest.approx(FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI)
    assert whole_portfolio["invested"] == 235000  # noqa: PLR2004 - the fixture's Purchases, fees included
    assert whole_portfolio["benchmarkHurdle"] == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    assert [h["name"] for h in whole_portfolio["hurdles"]] == ["ČSÚ CPI", "Eurostat HICP"]
    assert whole_portfolio["hurdles"][1]["value"] == pytest.approx(hurdle_on_1_jul(114.14 / 114.02))


def test_chart_with_fresh_data_warns_of_nothing_out_of_date(tmp_path: Path) -> None:
    fetch_everything(tmp_path)

    exit_code, _, stderr = run("--data-dir", tmp_path, "chart")

    assert (exit_code, warned_of_other_than_negative_cash(stderr)) == (0, "")
    assert page(tmp_path)["warnings"] == []


def test_chart_names_each_out_of_date_series_and_its_last_date_but_is_still_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetch_everything(tmp_path)
    monkeypatch.setattr(clock, "today", lambda: date(2021, 8, 2))

    exit_code, stdout, stderr = run("--data-dir", tmp_path, "chart")

    assert (exit_code, stdout) == (0, f"Chart written to {tmp_path / 'chart.html'}\n")
    stderr = warned_of_other_than_negative_cash(stderr)
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
    assert whole_portfolio_chart(tmp_path)["Amount invested"]["x"][-1] == "2021-08-02"


def test_chart_warns_only_of_the_series_that_are_out_of_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_everything(tmp_path)
    # Five business days after J&T Money's last price on Wed 30 Jun, but only four after the others' on Thu 1 Jul.
    monkeypatch.setattr(clock, "today", lambda: date(2021, 7, 8))

    exit_code, _, stderr = run("--data-dir", tmp_path, "chart")

    assert (exit_code, warned_of_other_than_negative_cash(stderr)) == (
        0,
        (
            "Out of date: J&T MONEY A CZK OPF (CZ0008473808) prices end on 2021-06-30; "
            "run inflation-station fetch-prices\n"
        ),
    )


def test_whole_portfolio_invested_and_hurdle_lines_hover_with_their_czk_value_only(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    lines = whole_portfolio_chart(tmp_path)
    for name in ("Whole Portfolio value", "Amount invested", "Inflation hurdle (ČSÚ CPI)"):
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
    assert (franklin["units"], franklin["notValued"]) == ("11.15", None)
    # Nothing is invested in a Holding, only in its Portfolio.
    assert not {"invested", "benchmarkHurdle", "relative"} & set(franklin)
    # Valued in CZK: no second currency.
    assert (ff_world["currencyValue"], ff_world["units"]) == (None, "79.9")


def test_funds_that_cannot_be_valued_come_last_saying_why(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "fetch-cpi")
    run("--data-dir", tmp_path, "chart")

    funds = page(tmp_path)["funds"]
    # The EUR funds have no rates, so only the CZK funds are valued.
    assert [f["isin"] for f in funds] == ["LU1756523376", "CZ0008473808", "LU0260870158", "LU1883872332"]
    franklin = funds[2]
    assert (franklin["notValued"], franklin["value"]) == ("no EUR rates stored", None)
    assert franklin["units"] == "11.15"
    assert funds[0]["notValued"] is None


def test_without_prices_a_fund_is_priced_in_the_currency_it_was_bought_in(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "chart")

    amundi = next(f for f in page(tmp_path)["funds"] if f["isin"] == "LU1883872332")
    assert (amundi["pricedIn"], amundi["notValued"]) == ("EUR", "no prices stored")


PORTU_EXPORT = Path(__file__).parent / "fixtures" / "portu_export.csv"


def test_each_portfolio_has_a_section_headed_by_its_platform_and_name_largest_value_first(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "import", PORTU_EXPORT)
    run("--data-dir", tmp_path, "chart")

    portfolios = page(tmp_path)["portfolios"]
    # A J&T Portfolio per Fund.
    assert [p["name"] for p in portfolios] == [
        "J&T Banka · FF - World Fund A-ACC-CZK",
        "J&T Banka · J&T MONEY A CZK OPF",
        "J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR",
        "Portu · Moje portfolio",
        "J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C)",
    ]
    jt, portu = portfolios[0], portfolios[3]
    jt_portfolios = [p for p in portfolios if p is not portu]
    assert [p["value"] for p in jt_portfolios] == pytest.approx([FF_WORLD, JT_MONEY, FRANKLIN, AMUNDI])
    assert sum(p["invested"] for p in jt_portfolios) == 235000  # noqa: PLR2004 - the fixture's seven Deposits
    assert sum(p["benchmarkHurdle"] for p in jt_portfolios) == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    assert [h["name"] for h in jt["hurdles"]] == ["ČSÚ CPI", "Eurostat HICP"]
    # Portu's money invested is its two Deposits. Its funds have no prices, so its value is its Cash: 8 116 CZK, and
    # no EUR.
    assert (portu["invested"], portu["value"], portu["notValued"]) == (15000, 8116, None)
    # It names what its value leaves out: its funds, and its Cash in currencies without rates.
    assert portu["leftOut"] == [
        "SXR7 GY (no prices stored)",
        "CSPX LN (no prices stored)",
        "ZPRS GY (no prices stored)",
        "USD Cash (no USD rates stored)",
    ]
    assert all(p["leftOut"] == [] for p in jt_portfolios)
    assert not any("managed" in p for p in portfolios)
    # Styled like the Whole Portfolio chart: value, amount invested and both hurdles, each in its role.
    assert {name: line["meta"] for name, line in by_name(jt["chart"]).items()} == {
        "Value": "value",
        "Amount invested": "invested",
        "Inflation hurdle (ČSÚ CPI)": "inflation",
        "Inflation hurdle (ČSÚ CPI, estimated)": "inflation",
        "Inflation hurdle (Eurostat HICP)": "inflation",
        "Inflation hurdle (Eurostat HICP, estimated)": "inflation",
    }
    assert [t["name"] for t in jt["relative"]] == ["real", "nominal"]


def test_each_platform_has_a_total_section_adding_up_its_portfolios_largest_value_first(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "import", PORTU_EXPORT)
    run("--data-dir", tmp_path, "chart")

    jt, portu = page(tmp_path)["platformTotals"]
    assert (jt["name"], portu["name"]) == ("J&T Banka", "Portu")
    assert jt["key"] != portu["key"]
    # J&T's four Portfolios, one per Fund, added together.
    assert jt["value"] == pytest.approx(FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI)
    assert jt["invested"] == 235000  # noqa: PLR2004 - the fixture's seven Deposits
    assert jt["benchmarkHurdle"] == pytest.approx(hurdle_on_1_jul(CSU_MAY))
    assert [h["name"] for h in jt["hurdles"]] == ["ČSÚ CPI", "Eurostat HICP"]
    assert (jt["notValued"], jt["leftOut"]) == (None, [])
    # Portu's one Portfolio is its total.
    (moje_portfolio,) = (p for p in page(tmp_path)["portfolios"] if p["name"] == "Portu · Moje portfolio")
    assert {k: v for k, v in portu.items() if k not in {"key", "name"}} == {
        k: v for k, v in moje_portfolio.items() if k not in {"key", "name"}
    }
    # Charted as a Portfolio is.
    assert {name: line["meta"] for name, line in by_name(jt["chart"]).items()} == {
        "Value": "value",
        "Amount invested": "invested",
        "Inflation hurdle (ČSÚ CPI)": "inflation",
        "Inflation hurdle (ČSÚ CPI, estimated)": "inflation",
        "Inflation hurdle (Eurostat HICP)": "inflation",
        "Inflation hurdle (Eurostat HICP, estimated)": "inflation",
    }
    assert by_name(jt["chart"])["Value"]["y"][-1] == pytest.approx(FF_WORLD + JT_MONEY + FRANKLIN + AMUNDI)
    assert [t["name"] for t in jt["relative"]] == ["real", "nominal"]


def test_a_platform_total_names_what_its_value_leaves_out_once(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    (jt,) = page(tmp_path)["platformTotals"]
    # Two of its Portfolios hold EUR Cash, neither valued without rates.
    assert jt["leftOut"] == [
        "FTIF-Franklin Technology Fund-A(acc)EUR (no EUR rates stored)",
        "AMUNDI FUNDS US PIONEER FUND - A EUR (C) (no EUR rates stored)",
        "EUR Cash (no EUR rates stored)",
    ]
    assert jt["value"] == pytest.approx(FF_WORLD + JT_MONEY)


def test_each_fund_section_is_a_holding_naming_its_portfolio(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "chart")

    assert {(f["portfolio"], f["name"]) for f in page(tmp_path)["funds"]} == {
        ("J&T Banka · FF - World Fund A-ACC-CZK", "FF - World Fund A-ACC-CZK"),
        ("J&T Banka · J&T MONEY A CZK OPF", "J&T MONEY A CZK OPF"),
        ("J&T Banka · FTIF-Franklin Technology Fund-A(acc)EUR", "FTIF-Franklin Technology Fund-A(acc)EUR"),
        ("J&T Banka · AMUNDI FUNDS US PIONEER FUND - A EUR (C)", "AMUNDI FUNDS US PIONEER FUND - A EUR (C)"),
    }


def test_holdings_show_units_but_no_amount_invested_or_hurdle(tmp_path: Path) -> None:
    fetch_everything(tmp_path)
    run("--data-dir", tmp_path, "import", PORTU_EXPORT)
    run("--data-dir", tmp_path, "chart")

    portu = [f for f in page(tmp_path)["funds"] if f["portfolio"] == "Portu · Moje portfolio"]
    assert [(f["isin"], f["units"], f["notValued"]) for f in portu] == [
        ("IE00B53QG562", "1", "no prices stored"),
        ("IE00B5BMR087", "0.25", "no prices stored"),
        ("IE00BCBJG560", "0.75", "no prices stored"),
    ]
    assert all(not {"invested", "benchmarkHurdle", "relative", "managed"} & set(f) for f in portu)


MOJE_PORTFOLIO = Portfolio(Platform.PORTU, "Moje portfolio", "Moje portfolio")


def portu_buy(fund: Fund, units: int, currency: str = "CZK") -> Purchase:
    """A Portu Purchase of `units` units at 100 on 13 Jun 2021."""
    return Purchase(
        MOJE_PORTFOLIO, fund, "2", date(2021, 6, 13), Decimal(units), Decimal(100), currency, Decimal(units * 100)
    )


def test_a_holding_has_no_line_of_its_own(tmp_path: Path) -> None:
    deposit = Deposit(MOJE_PORTFOLIO, "1", date(2021, 6, 13), Decimal(500), "CZK")
    t = timeline(
        Rows(deposits=[deposit], purchases=[portu_buy(Fund("IE00B53QG562", "SXR7 GY"), units=2)]),
        prices=[FundPrice(isin="IE00B53QG562", day=date(2021, 6, 13), price=Decimal(110), currency="CZK")],
        today=date(2021, 6, 14),
    )
    write_chart(t, tmp_path)

    (holding,) = page(tmp_path)["funds"]
    assert (holding["value"], holding["units"]) == (220, "2")
    assert "chart" not in holding
    # The Portfolio's value is its Holding plus its Cash: 300 CZK left of the Deposit.
    assert page(tmp_path)["portfolios"][0]["value"] == 520  # noqa: PLR2004
    assert page(tmp_path)["portfolios"][0]["leftOut"] == []


def ff_world(units: int, portfolio: str = "900000001") -> Purchase:
    """A J&T Purchase of `units` FF World units at 10 CZK, in Portfolio 900000001 on 13 Jun 2021."""
    return Purchase(
        portfolio=Portfolio(Platform.JT, portfolio, portfolio),
        fund=Fund("LU1756523376", "FF - World Fund A-ACC-CZK"),
        source_row_id="1",
        day=date(2021, 6, 13),
        units=Decimal(units),
        unit_price=Decimal(10),
        currency="CZK",
        amount=Decimal(units * 10),
    )


def test_one_fund_in_two_portfolios_is_two_holdings_each_naming_its_portfolio(tmp_path: Path) -> None:
    bought = [ff_world(units=2), ff_world(units=3, portfolio="900000002")]
    t = timeline(
        Rows(
            deposits=[Deposit(b.portfolio, "1", b.day, b.amount, "CZK") for b in bought],
            purchases=bought,
        ),
        prices=[FundPrice(isin="LU1756523376", day=date(2021, 6, 13), price=Decimal(10), currency="CZK")],
        today=date(2021, 6, 14),
    )
    write_chart(t, tmp_path)

    funds = page(tmp_path)["funds"]
    assert [(f["portfolio"], f["value"]) for f in funds] == [
        ("J&T Banka · 900000002", 30),
        ("J&T Banka · 900000001", 20),
    ]
    assert set(composition(tmp_path)) == {"J&T Banka · 900000001", "J&T Banka · 900000002", "Amount invested"}


def test_a_portfolio_with_nothing_valued_says_whether_its_funds_or_its_cash_are_missing(tmp_path: Path) -> None:
    cash_only = Portfolio(Platform.PORTU, "Cash only", "Cash only")
    rows = Rows(
        deposits=[
            Deposit(cash_only, "1", date(2021, 6, 13), Decimal(100), "USD"),
            Deposit(MOJE_PORTFOLIO, "1", date(2021, 6, 13), Decimal(100), "USD"),
        ],
        purchases=[
            replace(ff_world(units=1), currency="USD"),
            portu_buy(Fund("IE00B5BMR087", "CSPX LN"), units=1, currency="USD"),
        ],
    )
    write_chart(timeline(rows, today=date(2021, 6, 13)), tmp_path)

    assert {a["name"]: a["notValued"] for a in page(tmp_path)["portfolios"]} == {
        "J&T Banka · 900000001": "none of its funds or Cash valued",
        "Portu · Cash only": "none of its Cash valued",
        "Portu · Moje portfolio": "none of its funds or Cash valued",
    }
