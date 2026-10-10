from pathlib import Path
from typing import TYPE_CHECKING

import click

from inflation_station import clock, cnb, conseq, csu, jt
from inflation_station.chart import write_chart
from inflation_station.errors import InflationStationError
from inflation_station.price_check import price_warnings
from inflation_station.purchase import first_trade_dates, fund_names
from inflation_station.settings import Settings
from inflation_station.store import Store, database_exists
from inflation_station.valuation import CZK, NO_PRICES, Timeline, no_rates, timeline

if TYPE_CHECKING:
    from inflation_station.purchase import Purchase


@click.group()
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where the database lives (default: INFLATION_STATION_DATA_DIR from the environment or .env, else data/).",
)
@click.pass_context
def main(ctx: click.Context, data_dir: Path | None) -> None:
    ctx.obj = data_dir or Settings().data_dir


@main.command("import")
@click.argument("csv", type=click.Path(dir_okay=False, path_type=Path))
@click.pass_obj
def import_(data_dir: Path, csv: Path) -> None:
    """Import a J&T transaction export (CSV)."""
    try:
        purchases = jt.read_export(csv)
        result = Store(data_dir).add_purchases(purchases)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"{result.added} Purchases added, {result.already_present} already present.")


@main.command("fetch-prices")
@click.pass_obj
def fetch_prices(data_dir: Path) -> None:
    """Download the daily prices of every purchased fund from Conseq."""
    try:
        purchases = _stored_purchases(data_dir, "to fetch prices for")
        funds = fund_names(purchases)
        pages = conseq.fund_pages(funds)
        store = Store(data_dir)
        for isin, page in pages.items():
            # Stored fund by fund, so a later failure keeps what was fetched before it.
            result = store.add_fund_prices(conseq.price_history(isin, page))
            click.echo(
                f"{funds[isin]} ({isin}): {result.added} prices added, {result.already_present} already present."
            )
        warnings = price_warnings(purchases, store.fund_prices())
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    for warning in warnings:
        click.echo(f"Warning: {warning}", err=True)


@main.command("fetch-fx")
@click.pass_obj
def fetch_fx(data_dir: Path) -> None:
    """Download daily CZK rates from ČNB for every currency a purchased fund is priced in."""
    try:
        first_held = first_trade_dates(_stored_purchases(data_dir, "to fetch rates for"))
        first_held.pop(CZK, None)
        if not first_held:
            click.echo(f"Every Purchase is priced in {CZK}; no rates to fetch.")
            return
        store = Store(data_dir)
        for currency, first in first_held.items():
            stored = [r.day for r in store.fx_rates() if r.currency == currency]
            added = already_present = 0
            for month in cnb.months_to_fetch(first, clock.today(), stored):
                # Stored month by month, so a later failure keeps what was fetched before it.
                result = store.add_fx_rates(cnb.rates(currency, month))
                added += result.added
                already_present += result.already_present
            click.echo(f"{currency}: {added} rates added, {already_present} already present.")
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e


@main.command("fetch-cpi")
@click.pass_obj
def fetch_cpi(data_dir: Path) -> None:
    """Download ČSÚ's national CPI, for the inflation hurdle."""
    try:
        store = Store(data_dir)
        result = store.add_index_levels(csu.continuing(csu.cpi(), store.index_levels()))
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"ČSÚ CPI: {result.added} months added, {result.already_present} already present.")


@main.command()
@click.pass_obj
def chart(data_dir: Path) -> None:
    """Write an interactive HTML chart of the portfolio to the data directory."""
    try:
        purchases = _stored_purchases(data_dir, "to chart")
        store = Store(data_dir)
        prices = store.fund_prices()
        t = timeline(
            purchases,
            prices=prices,
            rates=store.fx_rates(),
            index_levels=store.index_levels(),
            today=clock.today(),
        )
        path = write_chart(t, data_dir)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    _report_not_valued(t, {p.currency for p in prices})
    click.echo(f"Chart written to {path}")


def _stored_purchases(data_dir: Path, purpose: str) -> list[Purchase]:
    """The stored Purchases; raises if there are none. Only reads: no database is created in an empty data directory."""
    purchases = Store(data_dir).purchases() if database_exists(data_dir) else []
    if not purchases:
        msg = f"no Purchases {purpose} yet; import an export first: inflation-station import <csv>"
        raise InflationStationError(msg)
    return purchases


def _report_not_valued(t: Timeline, price_currencies: set[str]) -> None:
    """Name the funds left out of the chart, grouped by why, on stderr."""
    rate_reasons = {no_rates(currency) for currency in price_currencies}
    by_reason: dict[str, list[str]] = {}
    for isin, reason in t.not_valued.items():
        by_reason.setdefault(reason, []).append(f"{t.fund_names[isin]} ({isin})")
    for reason, funds in by_reason.items():
        # A fund is left out for missing prices, missing rates, or prices in more than one currency.
        if reason == NO_PRICES:
            hint = "; run inflation-station fetch-prices"
        elif reason in rate_reasons:
            hint = "; run inflation-station fetch-fx"
        else:
            hint = ""
        click.echo(f"Not valued ({reason}{hint}): {', '.join(funds)}", err=True)
