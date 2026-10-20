from pathlib import Path

import click

from inflation_station import clock, cnb, csu, eurostat
from inflation_station.chart import portfolio_name, write_chart
from inflation_station.domain import Rows
from inflation_station.errors import InflationStationError
from inflation_station.freshness import out_of_date
from inflation_station.imports import read_files
from inflation_station.price_check import price_warnings
from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES
from inflation_station.price_sources import price_sources
from inflation_station.settings import Settings
from inflation_station.store import Store, database_exists
from inflation_station.valuation import CZK, NO_PRICES, Timeline, no_rates, timeline


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
    """Import J&T and Portu exports (CSV) and INVESTIKA statements (PDF, a cash and a holdings one per Portfolio).

    Each file's format is recognised from its content. If any file fails, nothing is imported.
    """
    try:
        imported = read_files(files)
        added = Store(data_dir).add_rows(imported)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    counts = {
        "Deposits": imported.deposits,
        "Purchases": imported.purchases,
        "Sales": imported.sales,
        "Fees": imported.fees,
        "Conversions": imported.conversions,
    }
    # Each kind of row the files hold; Purchases even when they hold none, so the import always says something.
    for kind, rows in counts.items():
        if rows or (kind == "Purchases" and not imported):
            click.echo(f"{added[kind].added} {kind} added, {added[kind].already_present} already present.")


@main.command("fetch-prices")
@click.pass_obj
def fetch_prices(data_dir: Path) -> None:
    """Download the daily prices of every purchased or held fund, from Conseq or Yahoo Finance."""
    try:
        rows = _read_rows(data_dir)
        names = _fund_names(rows)
        sources = price_sources(names)
        store = Store(data_dir)
        for isin, source in sources.items():
            # Stored fund by fund, so a later failure keeps what was fetched before it.
            result = store.add_fund_prices(source.fetch())
            click.echo(
                f"{names[isin]} ({isin}): {result.added} prices added, {result.already_present} already present."
            )
        warnings = price_warnings(rows, store.fund_prices(), fund_names=names, sources=sources)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    for warning in warnings:
        click.echo(f"Warning: {warning}", err=True)


@main.command("fetch-fx")
@click.pass_obj
def fetch_fx(data_dir: Path) -> None:
    """Download daily CZK rates from ČNB for every currency a purchased fund is priced in or Cash is held in."""
    try:
        first_held = _stored_rows(data_dir, "to fetch rates for").first_days()
        first_held.pop(CZK, None)
        if not first_held:
            click.echo(f"Every Purchase and all Cash is in {CZK}; no rates to fetch.")
            return
        store = Store(data_dir)
        for currency, first in sorted(first_held.items()):
            stored = [r.day for r in store.fx_rates() if (r.from_currency, r.to_currency) == (currency, CZK)]
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
    try:
        store = Store(data_dir)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
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
    """Write an interactive HTML chart of the Whole Portfolio to the data directory."""
    try:
        rows = _stored_rows(data_dir, "to chart")
        store = Store(data_dir)
        prices = store.fund_prices()
        rates = store.fx_rates()
        index_levels = store.index_levels()
        today = clock.today()
        t = timeline(rows, prices=prices, rates=rates, index_levels=index_levels, today=today)
        # Only warnings, on stderr and on the page: the chart is still right up to each series' last point.
        warnings = out_of_date(
            prices=prices, rates=rates, index_levels=index_levels, fund_names=t.fund_names, today=today
        )
        path = write_chart(t, data_dir, warnings=warnings)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    _report_not_valued(t, {p.currency for p in prices} | set(t.cash))
    _report_negative_cash(t)
    for warning in warnings:
        click.echo(f"Out of date: {warning}", err=True)
    click.echo(f"Chart written to {path}")


def _stored_rows(data_dir: Path, purpose: str) -> Rows:
    """The stored rows; raises if there are none."""
    rows = _read_rows(data_dir)
    if not rows:
        msg = f"no Purchases or Deposits {purpose} yet; import first: inflation-station import <file>..."
        raise InflationStationError(msg)
    return rows


def _fund_names(rows: Rows) -> dict[str, str]:
    """The name of every Fund bought or sold, by ISIN; raises if there are none."""
    names = {isin: fund.name for isin, fund in rows.funds().items()}
    if not names:
        msg = "no Purchases or Sales to fetch prices for yet; import first: inflation-station import <file>..."
        raise InflationStationError(msg)
    return names


def _read_rows(data_dir: Path) -> Rows:
    """The stored rows, possibly none. Only reads: no database is created in an empty data directory."""
    return Store(data_dir).rows() if database_exists(data_dir) else Rows()


def _report_not_valued(t: Timeline, currencies: set[str]) -> None:
    """Name the funds and Cash left out of the chart, grouped by why, on stderr."""
    rate_reasons = {no_rates(currency) for currency in currencies}
    by_reason: dict[str, list[str]] = {}
    for isin, reason in t.not_valued.items():
        by_reason.setdefault(reason, []).append(f"{t.fund_names[isin]} ({isin})")
    for currency, reason in t.cash_not_valued.items():
        by_reason.setdefault(reason, []).append(f"{currency} Cash")
    for reason, left_out in by_reason.items():
        # A fund is left out for missing prices, missing rates, or prices in more than one currency; Cash only for
        # missing rates.
        if reason == NO_PRICES:
            hint = "; run inflation-station fetch-prices"
        elif reason in rate_reasons:
            hint = "; run inflation-station fetch-fx"
        else:
            hint = ""
        click.echo(f"Not valued ({reason}{hint}): {', '.join(left_out)}", err=True)


def _report_negative_cash(t: Timeline) -> None:
    """Name the days each Portfolio's Cash in a currency was negative, on stderr: a warning, not a failure."""
    by_cash: dict[tuple[str, str], list[str]] = {}
    for n in t.negative_cash:
        days = n.first_day.isoformat() + ("" if n.last_day == n.first_day else f" to {n.last_day}")
        by_cash.setdefault((portfolio_name(n.portfolio), n.currency), []).append(days)
    for (portfolio, currency), days in by_cash.items():
        click.echo(f"Negative Cash ({currency}): {portfolio} on {', '.join(days)}", err=True)
