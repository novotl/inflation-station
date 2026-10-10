from pathlib import Path
from typing import TYPE_CHECKING

import click

from inflation_station import clock, conseq, jt
from inflation_station.chart import write_chart
from inflation_station.errors import InflationStationError
from inflation_station.price_check import price_warnings
from inflation_station.purchase import fund_names
from inflation_station.settings import Settings
from inflation_station.store import Store, database_exists
from inflation_station.valuation import NO_PRICES, Timeline, timeline

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


@main.command()
@click.pass_obj
def chart(data_dir: Path) -> None:
    """Write an interactive HTML chart of the portfolio to the data directory."""
    try:
        purchases = _stored_purchases(data_dir, "to chart")
        t = timeline(purchases, prices=Store(data_dir).fund_prices(), today=clock.today())
        path = write_chart(t, data_dir)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    _report_not_valued(t)
    click.echo(f"Chart written to {path}")


def _stored_purchases(data_dir: Path, purpose: str) -> list[Purchase]:
    """The stored Purchases; raises if there are none. Only reads: no database is created in an empty data directory."""
    purchases = Store(data_dir).purchases() if database_exists(data_dir) else []
    if not purchases:
        msg = f"no Purchases {purpose} yet; import an export first: inflation-station import <csv>"
        raise InflationStationError(msg)
    return purchases


def _report_not_valued(t: Timeline) -> None:
    """Name the funds left out of the chart, grouped by why, on stderr."""
    by_reason: dict[str, list[str]] = {}
    for isin, reason in t.not_valued.items():
        by_reason.setdefault(reason, []).append(f"{t.fund_names[isin]} ({isin})")
    for reason, funds in by_reason.items():
        hint = "; run inflation-station fetch-prices" if reason == NO_PRICES else ""
        click.echo(f"Not valued ({reason}{hint}): {', '.join(funds)}", err=True)
