"""Reads the files platforms export, recognising each file's format from its content."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inflation_station import investika, jt, portu
from inflation_station.errors import InflationStationError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from inflation_station.ledger import LedgerEntry
    from inflation_station.purchase import Purchase

PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class Imported:
    """What a set of exports holds: Purchases from Platforms where you pick the funds, and Managed Accounts' ledgers."""

    purchases: list[Purchase]
    ledger: list[LedgerEntry]


def read_files(paths: Iterable[Path]) -> Imported:
    """Read J&T and Portu exports (CSV) and INVESTIKA statement pairs (PDF). Raises if any file fails to read."""
    purchases: list[Purchase] = []
    ledger: list[LedgerEntry] = []
    statements = []
    for path in paths:
        if _is_pdf(path):
            statements.append(investika.read_pdf(path))
        elif portu.is_export(path):
            ledger.extend(portu.read_export(path))
        else:
            purchases.extend(jt.read_export(path))
    return Imported(purchases=purchases + investika.purchases(statements), ledger=ledger)


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError as e:
        msg = f"cannot read {path}: {e}"
        raise InflationStationError(msg) from e
