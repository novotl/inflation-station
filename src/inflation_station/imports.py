"""Reads Purchases from the files platforms export, recognising each file's format from its content."""

from typing import TYPE_CHECKING

from inflation_station import investika, jt
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from inflation_station.purchase import Purchase

PDF_SIGNATURE = b"%PDF-"


def read_purchases(paths: Iterable[Path]) -> list[Purchase]:
    """The Purchases in J&T exports (CSV) and Investika statement pairs (PDF). Raises if any file fails to read."""
    purchases: list[Purchase] = []
    statements = []
    for path in paths:
        if _is_pdf(path):
            statements.append(investika.read_pdf(path))
        else:
            purchases.extend(jt.read_export(path))
    return purchases + investika.purchases(statements)


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
