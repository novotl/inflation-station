from pathlib import Path
from typing import TYPE_CHECKING

import click

from inflation_station import clock, jt
from inflation_station.chart import write_chart
from inflation_station.errors import InflationStationError
from inflation_station.settings import Settings
from inflation_station.store import Store, database_exists
from inflation_station.valuation import timeline

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


@main.command()
@click.pass_obj
def chart(data_dir: Path) -> None:
    """Write an interactive HTML chart of the portfolio to the data directory."""
    try:
        path = write_chart(timeline(_stored_purchases(data_dir), today=clock.today()), data_dir)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Chart written to {path}")


def _stored_purchases(data_dir: Path) -> list[Purchase]:
    """The stored Purchases; raises if there are none. Only reads: no database is created in an empty data directory."""
    purchases = Store(data_dir).purchases() if database_exists(data_dir) else []
    if not purchases:
        msg = "no Purchases to chart yet; import an export first: inflation-station import <csv>"
        raise InflationStationError(msg)
    return purchases
