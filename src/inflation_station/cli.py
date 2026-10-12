from pathlib import Path
from typing import TYPE_CHECKING

import click

from inflation_station import clock, cnb, csu, eurostat
from inflation_station.chart import write_chart
from inflation_station.errors import InflationStationError
from inflation_station.freshness import out_of_date
from inflation_station.imports import read_files
from inflation_station.price_check import price_warnings
from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES
from inflation_station.price_sources import price_sources
from inflation_station.purchase import first_trade_dates
from inflation_station.settings import Settings
from inflation_station.store import Store, database_exists
from inflation_station.valuation import CZK, NO_PRICES, Timeline, all_fund_names, no_rates, timeline

if TYPE_CHECKING:
    from inflation_station.ledger import LedgerEntry
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
@click.argument("files", nargs=-1, required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.pass_obj
def import_(data_dir: Path, files: tuple[Path, ...]) -> None:
    """Import J&T and Portu exports (CSV) and INVESTIKA statements (PDF, a cash and a holdings one per contract).

    Each file's format is recognised from its content. If any file fails, nothing is imported.
    """
    try:
        imported = read_files(files)
        store = Store(data_dir)
        purchases = store.add_purchases(imported.purchases)
        ledger = store.add_ledger_entries(imported.ledger)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    if imported.purchases or not imported.ledger:
        click.echo(f"{purchases.added} Purchases added, {purchases.already_present} already present.")
    if imported.ledger:
        click.echo(f"{ledger.added} ledger entries added, {ledger.already_present} already present.")


@main.command("fetch-prices")
@click.pass_obj
def fetch_prices(data_dir: Path) -> None:
    """Download the daily prices of every purchased or held fund, from Conseq or Yahoo Finance."""
    try:
        purchases, ledger = _stored_buys_and_sells(data_dir)
        funds = all_fund_names(purchases, ledger)
        sources = price_sources(funds)
        store = Store(data_dir)
        for isin, source in sources.items():
            # Stored fund by fund, so a later failure keeps what was fetched before it.
            result = store.add_fund_prices(source.fetch())
            click.echo(
                f"{funds[isin]} ({isin}): {result.added} prices added, {result.already_present} already present."
            )
        published_by = {isin: source.name for isin, source in sources.items()}
        warnings = price_warnings(purchases, ledger, store.fund_prices(), published_by)
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
    """Download ČSÚ's national CPI and Eurostat's HICP for Czechia, for the inflation hurdles."""
    store = Store(data_dir)
    fetchers = {
        CSU_CPI: lambda: csu.continuing(csu.cpi(), store.index_levels()),
        EUROSTAT_HICP: eurostat.hicp,
    }
    failed = False
    for series, fetch in fetchers.items():
        # Stored series by series, so one failing keeps the other.
        try:
            result = store.add_index_levels(fetch())
        except InflationStationError as e:
            click.echo(f"Error: {NAMES[series]}: {e}", err=True)
            failed = True
            continue
        click.echo(f"{NAMES[series]}: {result.added} months added, {result.already_present} already present.")
    if failed:
        raise click.exceptions.Exit(1)


@main.command()
@click.pass_obj
def chart(data_dir: Path) -> None:
    """Write an interactive HTML chart of the portfolio to the data directory."""
    try:
        purchases, ledger = _stored_purchases_and_ledger(data_dir)
        store = Store(data_dir)
        prices = store.fund_prices()
        rates = store.fx_rates()
        index_levels = store.index_levels()
        today = clock.today()
        t = timeline(purchases, ledger=ledger, prices=prices, rates=rates, index_levels=index_levels, today=today)
        # Only warnings, on stderr and on the page: the chart is still right up to each series' last point.
        warnings = out_of_date(
            prices=prices, rates=rates, index_levels=index_levels, fund_names=t.fund_names, today=today
        )
        path = write_chart(t, data_dir, warnings=warnings)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    _report_not_valued(t, {p.currency for p in prices})
    for warning in warnings:
        click.echo(f"Out of date: {warning}", err=True)
    click.echo(f"Chart written to {path}")


def _stored_purchases(data_dir: Path, purpose: str) -> list[Purchase]:
    """The stored Purchases; raises if there are none. Only reads: no database is created in an empty data directory."""
    purchases = Store(data_dir).purchases() if database_exists(data_dir) else []
    if not purchases:
        msg = f"no Purchases {purpose} yet; import first: inflation-station import <file>..."
        raise InflationStationError(msg)
    return purchases


def _stored_buys_and_sells(data_dir: Path) -> tuple[list[Purchase], list[LedgerEntry]]:
    """The stored Purchases and ledger entries; raises if no fund was bought in either. Only reads, like
    `_stored_purchases`."""
    store = Store(data_dir) if database_exists(data_dir) else None
    purchases, ledger = (store.purchases(), store.ledger()) if store else ([], [])
    if not purchases and not any(e.isin for e in ledger):
        msg = (
            "no Purchases or Managed Account buys to fetch prices for yet; import first: "
            "inflation-station import <file>..."
        )
        raise InflationStationError(msg)
    return purchases, ledger


def _stored_purchases_and_ledger(data_dir: Path) -> tuple[list[Purchase], list[LedgerEntry]]:
    """The stored Purchases and ledger entries; raises if there are neither. Only reads, like `_stored_purchases`."""
    store = Store(data_dir) if database_exists(data_dir) else None
    purchases, ledger = (store.purchases(), store.ledger()) if store else ([], [])
    if not purchases and not ledger:
        msg = "no Purchases or Deposits to chart yet; import first: inflation-station import <file>..."
        raise InflationStationError(msg)
    return purchases, ledger


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
