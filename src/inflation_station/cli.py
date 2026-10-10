import argparse
import os
import sys
from pathlib import Path

from inflation_station import jt
from inflation_station.errors import InflationStationError
from inflation_station.store import Store

DATA_DIR_ENV = "INFLATION_STATION_DATA_DIR"
DEFAULT_DATA_DIR = Path("data")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.command(args)
    except InflationStationError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inflation-station")
    parser.add_argument(
        "--data-dir",
        type=Path,
        help=f"where the database lives (default: ${DATA_DIR_ENV}, else ./{DEFAULT_DATA_DIR})",
    )
    commands = parser.add_subparsers(required=True, metavar="command")

    import_ = commands.add_parser("import", help="import a J&T transaction export (CSV)")
    import_.add_argument("csv", type=Path)
    import_.set_defaults(command=_import)

    return parser


def _import(args: argparse.Namespace) -> None:
    purchases = jt.read_export(args.csv)
    result = _store(args).add_purchases(purchases)
    sys.stdout.write(f"{result.added} Purchases added, {result.already_present} already present.\n")


def _store(args: argparse.Namespace) -> Store:
    data_dir = args.data_dir or Path(os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR)
    return Store(data_dir)
