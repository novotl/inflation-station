from pathlib import Path

import click

from inflation_station import jt
from inflation_station.errors import InflationStationError
from inflation_station.settings import Settings
from inflation_station.store import Store


@click.group()
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Where the database lives (default: INFLATION_STATION_DATA_DIR from the environment or .env, else data/).",
)
@click.pass_context
def main(ctx: click.Context, data_dir: Path | None) -> None:
    ctx.obj = data_dir


@main.command("import")
@click.argument("csv", type=click.Path(dir_okay=False, path_type=Path))
@click.pass_obj
def import_(data_dir: Path | None, csv: Path) -> None:
    """Import a J&T transaction export (CSV)."""
    try:
        purchases = jt.read_export(csv)
        result = Store(data_dir or Settings().data_dir).add_purchases(purchases)
    except InflationStationError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"{result.added} Purchases added, {result.already_present} already present.")
