"""Reads the files platforms export, recognising each file's format from its content."""

from typing import TYPE_CHECKING

from inflation_station import investika, jt, portu
from inflation_station.domain import Rows
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

PDF_SIGNATURE = b"%PDF-"


def read_files(paths: Iterable[Path]) -> Rows:
    """Read J&T and Portu exports (CSV) and INVESTIKA statement pairs (PDF). Raises if any file fails to read."""
    rows = Rows()
    statements = []
    for path in paths:
        if _is_pdf(path):
            statements.append(investika.read_pdf(path))
        elif portu.is_export(path):
            rows += portu.read_export(path)
        else:
            rows += jt.read_export(path)
    return rows + investika.rows(statements)


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
