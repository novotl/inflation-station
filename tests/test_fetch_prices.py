import re
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import ANY

import pytest
from click.testing import CliRunner
from test_chart import composition, page

from inflation_station import conseq, yahoo
from inflation_station.cli import main
from inflation_station.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "jt_export.csv"
PORTU_EXPORT = FIXTURES / "portu_export.csv"
FF_WORLD_PAGE = "https://www.conseq.cz/investice/prehled-fondu/ff-world-fund-czk"
FF_WORLD_PRICES = "https://www.conseq.cz/Conseq/Pricehist.ashx?productid=9613&culture=cs-CZ"

# Each fixture fund and the number of prices recorded for it, in the order fetch-prices reports them (by ISIN).
RECORDED_PRICES = {
    "J&T MONEY A CZK OPF (CZ0008473808)": 25,
    "FTIF-Franklin Technology Fund-A(acc)EUR (LU0260870158)": 65,
    "FF - World Fund A-ACC-CZK (LU1756523376)": 66,
    "AMUNDI FUNDS US PIONEER FUND - A EUR (C) (LU1883872332)": 60,
}


def run(*args: str | Path) -> tuple[int, str, str]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    result = CliRunner().invoke(main, [str(a) for a in args])
    return result.exit_code, result.stdout, result.stderr


def report(*, first_fetch: bool) -> str:
    """What fetch-prices prints for the fixture funds, on the first fetch or on a repeat."""
    return "".join(
        f"{fund}: {n if first_fetch else 0} prices added, {0 if first_fetch else n} already present.\n"
        for fund, n in RECORDED_PRICES.items()
    )


def test_fetch_prices_stores_prices_for_every_purchased_fund(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices") == (0, report(first_fetch=True), "")


def test_refetching_adds_no_duplicates(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")

    assert run("--data-dir", tmp_path, "fetch-prices") == (0, report(first_fetch=False), "")


def test_fetch_prices_with_an_empty_database_fails_with_a_readable_message(tmp_path: Path) -> None:
    assert run("--data-dir", tmp_path, "fetch-prices") == (
        1,
        "",
        (
            "Error: no Purchases or Managed Portfolio buys to fetch prices for yet; import first: "
            "inflation-station import <file>...\n"
        ),
    )


def test_an_unmapped_fund_fails_naming_it_and_how_to_add_it(tmp_path: Path) -> None:
    export = tmp_path / "unmapped.csv"
    export.write_text(EXPORT.read_text(encoding="utf-8").replace("CZ0008473808", "CZ0000000000"), encoding="utf-8")
    run("--data-dir", tmp_path, "import", export)

    code, stdout, stderr = run("--data-dir", tmp_path, "fetch-prices")

    assert (code, stdout) == (1, "")
    assert stderr == (
        "Error: no price source for J&T MONEY A CZK OPF (CZ0000000000). If Conseq has the fund, find it on "
        "https://www.conseq.cz/investice/prehled-fondu, check the ISIN on its page, and add the page's URL to "
        f'{conseq.FUND_PAGES} as: CZ0000000000 = "<fund page URL>". If it is exchange-traded, add the Yahoo Finance '
        f'ticker of the listing in the currency it was bought in to {yahoo.TICKERS} as: CZ0000000000 = "<ticker>"\n'
    )


def test_a_fund_listed_by_both_conseq_and_yahoo_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tickers = tmp_path / "yahoo_funds.toml"
    tickers.write_text(yahoo.TICKERS.read_text(encoding="utf-8") + 'LU1756523376 = "FFW.DE"\n', encoding="utf-8")
    monkeypatch.setattr(yahoo, "TICKERS", tickers)
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices") == (
        1,
        "",
        (
            f"Error: FF - World Fund A-ACC-CZK (LU1756523376) is listed in both {conseq.FUND_PAGES} and {tickers}; "
            "remove it from one of them\n"
        ),
    )


def test_an_isin_never_purchased_or_held_listed_by_both_conseq_and_yahoo_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FF America (LU0979392767) has a Conseq page but is not in the export.
    tickers = tmp_path / "yahoo_funds.toml"
    tickers.write_text(yahoo.TICKERS.read_text(encoding="utf-8") + 'LU0979392767 = "FFA.DE"\n', encoding="utf-8")
    monkeypatch.setattr(yahoo, "TICKERS", tickers)
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices") == (
        1,
        "",
        f"Error: LU0979392767 is listed in both {conseq.FUND_PAGES} and {tickers}; remove it from one of them\n",
    )


def test_a_fund_page_showing_another_isin_fails_naming_both(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[FF_WORLD_PAGE] = FIXTURES / "conseq" / "ff-america-fund-hedged-czk.html"
    run("--data-dir", tmp_path, "import", EXPORT)

    code, _, stderr = run("--data-dir", tmp_path, "fetch-prices")

    assert code == 1
    assert stderr == (
        f"Error: the Conseq page {FF_WORLD_PAGE} is for ISIN LU0979392767, not LU1756523376; "
        f"fix the mapping in {conseq.FUND_PAGES}\n"
    )


def test_refetching_keeps_stored_prices_when_conseq_changes_them(tmp_path: Path, recorded: dict[str, Path]) -> None:
    run("--data-dir", tmp_path, "import", EXPORT)
    run("--data-dir", tmp_path, "fetch-prices")
    recorded[FF_WORLD_PRICES] = with_every_price_set_to("1", recorded[FF_WORLD_PRICES], tmp_path / "changed.xlsx")

    run("--data-dir", tmp_path, "fetch-prices")
    run("--data-dir", tmp_path, "chart")

    # 79.90 units at the stored price of 1 463 CZK on 1 Jul 2021, not at Conseq's changed price of 1.
    assert composition(tmp_path)["FF - World Fund A-ACC-CZK"]["y"][-1] == pytest.approx(79.90 * 1463)


def with_every_price_set_to(price: str, xlsx: Path, changed: Path) -> Path:
    """A copy of the price history `xlsx` at `changed`, as if Conseq had changed every price to `price`."""
    sheet = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(xlsx) as original, zipfile.ZipFile(changed, "w") as copy:
        for name in original.namelist():
            data = original.read(name)
            if name == sheet:
                data = re.sub(rb'(<c r="B(?!1")\d+"[^>]*><v>)[^<]*', rb"\g<1>" + price.encode(), data)
            copy.writestr(name, data)
    return changed


def test_a_fund_page_without_an_isin_fails_saying_the_page_may_have_changed(
    tmp_path: Path, recorded: dict[str, Path]
) -> None:
    recorded[FF_WORLD_PAGE] = FIXTURES / "conseq" / "README.md"
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices")[::2] == (
        1,
        f"Error: cannot find an ISIN on the Conseq page {FF_WORLD_PAGE}; has the page changed?\n",
    )


def test_a_price_history_that_is_not_a_spreadsheet_fails_naming_its_url(
    tmp_path: Path, recorded: dict[str, Path]
) -> None:
    recorded[FF_WORLD_PRICES] = FIXTURES / "conseq" / "README.md"
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices")[::2] == (
        1,
        f"Error: cannot read the price history {FF_WORLD_PRICES}: File is not a zip file\n",
    )


def with_ff_world_bought_at(price: str, tmp_path: Path, currency: str = "CZK") -> Path:
    """The fixture export, with the 15 Jun 2021 FF World Purchase (Conseq: 1 436 CZK) at `price` `currency` instead."""
    export = tmp_path / "changed.csv"
    original = EXPORT.read_text(encoding="utf-8")
    export.write_text(original.replace('"1 436,00";CZK', f'"{price}";{currency}'), encoding="utf-8")
    return export


def test_a_purchase_price_more_than_half_a_percent_off_conseq_is_warned_about(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", with_ff_world_bought_at("1 444,00", tmp_path))

    assert run("--data-dir", tmp_path, "fetch-prices") == (
        0,
        report(first_fetch=True),
        (
            "Warning: FF - World Fund A-ACC-CZK (LU1756523376) bought on 2021-06-15 at 1444.00 CZK in the export, "
            "but Conseq's price that day is 1436 CZK (0.56 % off).\n"
        ),
    )


def test_a_purchase_priced_in_another_currency_than_conseq_is_warned_about(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", with_ff_world_bought_at("1 436,00", tmp_path, currency="EUR"))

    assert run("--data-dir", tmp_path, "fetch-prices") == (
        0,
        report(first_fetch=True),
        (
            "Warning: FF - World Fund A-ACC-CZK (LU1756523376) bought on 2021-06-15 at 1436.00 EUR in the export, "
            "but Conseq's price that day is 1436 CZK (a different currency).\n"
        ),
    )


def test_a_purchase_price_within_half_a_percent_of_conseq_is_not_warned_about(tmp_path: Path) -> None:
    # 1 443 is 0.49 % above Conseq's 1 436.
    run("--data-dir", tmp_path, "import", with_ff_world_bought_at("1 443,00", tmp_path))

    assert run("--data-dir", tmp_path, "fetch-prices") == (0, report(first_fetch=True), "")


def test_the_warning_changes_no_data(tmp_path: Path) -> None:
    warned, plain = tmp_path / "warned", tmp_path / "plain"
    run("--data-dir", warned, "import", with_ff_world_bought_at("1 444,00", tmp_path))
    run("--data-dir", plain, "import", EXPORT)

    for data_dir in (warned, plain):
        run("--data-dir", data_dir, "fetch-prices")
        run("--data-dir", data_dir, "chart")

    # Valued at Conseq's prices either way, and no price stored differently.
    assert page(warned) == page(plain)
    assert run("--data-dir", warned, "fetch-prices") == (0, report(first_fetch=False), ANY)


def test_a_purchase_on_a_day_without_a_conseq_price_is_not_checked(tmp_path: Path) -> None:
    # Saturday 19 Jun 2021, when Conseq has no price, at a price far from any Conseq price.
    export = with_ff_world_bought_at("9 999,00", tmp_path)
    saturday = "00:00 19.06.2021;Investice klienta (vklad);FF - World"
    export.write_text(
        export.read_text(encoding="utf-8").replace("00:00 15.06.2021;Investice klienta (vklad);FF - World", saturday),
        encoding="utf-8",
    )
    run("--data-dir", tmp_path, "import", export)

    assert run("--data-dir", tmp_path, "fetch-prices") == (0, report(first_fetch=True), "")


def test_a_conseq_price_of_zero_is_not_checked(tmp_path: Path, recorded: dict[str, Path]) -> None:
    recorded[FF_WORLD_PRICES] = with_every_price_set_to("0", recorded[FF_WORLD_PRICES], tmp_path / "zero.xlsx")
    run("--data-dir", tmp_path, "import", EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices") == (0, report(first_fetch=True), "")


# The Portu fixture's ETFs, by ISIN, and the number of daily closes recorded for each.
PORTU_REPORT = (
    "SXR7 GY (IE00B53QG562): 85 prices added, 0 already present.\n"
    "CSPX LN (IE00B5BMR087): 84 prices added, 0 already present.\n"
    "ZPRS GY (IE00BCBJG560): 85 prices added, 0 already present.\n"
)


def test_fetch_prices_stores_yahoo_closes_for_funds_held_in_a_managed_portfolio(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", PORTU_EXPORT)

    code, stdout, _ = run("--data-dir", tmp_path, "fetch-prices")

    assert (code, stdout) == (0, PORTU_REPORT)
    stored = {(p.isin, p.day): (p.price, p.currency) for p in Store(tmp_path).fund_prices()}
    assert stored["IE00B53QG562", date(2021, 6, 30)] == (Decimal("143.72"), "EUR")
    assert stored["IE00B5BMR087", date(2021, 6, 30)] == (Decimal("435.94"), "USD")


def test_portu_buys_and_sells_are_checked_against_yahoo(tmp_path: Path) -> None:
    # The fixture's prices are made up, so every buy and sell is off Yahoo's close.
    run("--data-dir", tmp_path, "import", PORTU_EXPORT)

    assert run("--data-dir", tmp_path, "fetch-prices")[2] == (
        "Warning: SXR7 GY (IE00B53QG562) bought on 2021-03-03 at 120.0000 EUR in the export, "
        "but Yahoo Finance's price that day is 129.2 EUR (7.12 % off).\n"
        "Warning: CSPX LN (IE00B5BMR087) bought on 2021-03-03 at 400.0000 USD in the export, "
        "but Yahoo Finance's price that day is 390.86 USD (2.34 % off).\n"
        "Warning: ZPRS GY (IE00BCBJG560) bought on 2021-03-03 at 80.0000 EUR in the export, "
        "but Yahoo Finance's price that day is 82.46 EUR (2.98 % off).\n"
        "Warning: ZPRS GY (IE00BCBJG560) bought on 2021-03-03 at 80.0000 EUR in the export, "
        "but Yahoo Finance's price that day is 82.46 EUR (2.98 % off).\n"
        "Warning: ZPRS GY (IE00BCBJG560) sold on 2021-04-15 at 84.0000 EUR in the export, "
        "but Yahoo Finance's price that day is 86.35 EUR (2.72 % off).\n"
    )


def test_a_portu_buy_within_half_a_percent_of_yahoo_is_not_warned_about(tmp_path: Path) -> None:
    # Only the SXR7 buy, at 129.80: 0.46 % above Yahoo's 129.20.
    export = tmp_path / "portu.csv"
    lines = PORTU_EXPORT.read_text(encoding="utf-8").splitlines(keepends=True)
    sxr7 = next(line for line in lines if "SXR7 GY" in line).replace("120,0000", "129,8000")
    export.write_text(lines[0] + sxr7, encoding="utf-8")
    run("--data-dir", tmp_path, "import", export)

    assert run("--data-dir", tmp_path, "fetch-prices") == (
        0,
        "SXR7 GY (IE00B53QG562): 85 prices added, 0 already present.\n",
        "",
    )


def test_jt_and_portu_funds_are_fetched_together(tmp_path: Path) -> None:
    run("--data-dir", tmp_path, "import", EXPORT, PORTU_EXPORT)

    code, stdout, _ = run("--data-dir", tmp_path, "fetch-prices")

    assert code == 0
    assert stdout.splitlines() == sorted(
        (report(first_fetch=True) + PORTU_REPORT).splitlines(), key=lambda line: line.split("(")[-1]
    )
