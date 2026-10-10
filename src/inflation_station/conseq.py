"""Downloads fund prices from Conseq: the fund page (to check its ISIN and find the download link), then the `.xlsx`."""

import html
import re
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from inflation_station import web
from inflation_station.errors import InflationStationError
from inflation_station.fund_price import FundPrice

if TYPE_CHECKING:
    from collections.abc import Mapping

# The hand-edited mapping from ISIN to Conseq fund page.
FUND_PAGES = Path(__file__).parent / "conseq_funds.toml"
FUND_LIST = "https://www.conseq.cz/investice/prehled-fondu"

_PAGE_ISIN = re.compile(r"<dt>\s*ISIN:\s*</dt>\s*<dd>\s*([^<\s]+)\s*</dd>")
_PRICE_HISTORY_LINK = re.compile(r"""href\s*=\s*['"]([^'"]*Pricehist\.ashx\?productid=[^'"]*)['"]""")

_SHEET = "xl/worksheets/sheet1.xml"
_SHARED_STRINGS = "xl/sharedStrings.xml"
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COLUMNS = "ABC"
_HEADER = ["Datum", "Cena", "Měna"]
# Excel stores dates as days since this one (which accounts for Excel's phantom 29 Feb 1900).
_EXCEL_EPOCH = date(1899, 12, 30)


def fund_pages(funds: Mapping[str, str]) -> dict[str, str]:
    """The Conseq fund page of each fund in `funds` (ISIN -> fund name). Raises naming every fund without one."""
    mapping = tomllib.loads(FUND_PAGES.read_text(encoding="utf-8"))
    unmapped = [isin for isin in funds if isin not in mapping]
    if unmapped:
        names = ", ".join(f"{funds[isin]} ({isin})" for isin in unmapped)
        lines = ", ".join(f'{isin} = "<fund page URL>"' for isin in unmapped)
        msg = (
            f"no Conseq fund page for {names}. Find the fund on {FUND_LIST}, check the ISIN on its page, "
            f"and add the page's URL to {FUND_PAGES} as: {lines}"
        )
        raise InflationStationError(msg)
    return {isin: mapping[isin] for isin in funds}


def price_history(isin: str, page_url: str) -> list[FundPrice]:
    """Every price Conseq publishes for the fund, after checking that `page_url` is the page of `isin`."""
    page = web.fetch(page_url).decode("utf-8", errors="replace")
    shown = _PAGE_ISIN.search(page)
    if not shown:
        msg = f"cannot find an ISIN on the Conseq page {page_url}; has the page changed?"
        raise InflationStationError(msg)
    if shown.group(1) != isin:
        msg = f"the Conseq page {page_url} is for ISIN {shown.group(1)}, not {isin}; fix the mapping in {FUND_PAGES}"
        raise InflationStationError(msg)
    link = _PRICE_HISTORY_LINK.search(page)
    if not link:
        msg = f"cannot find the price history download on the Conseq page {page_url}; has the page changed?"
        raise InflationStationError(msg)
    xlsx_url = urljoin(page_url, html.unescape(link.group(1)))
    try:
        return _read_price_history(isin, web.fetch(xlsx_url))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        msg = f"cannot read the price history {xlsx_url}: {e}"
        raise InflationStationError(msg) from e


def _read_price_history(isin: str, xlsx: bytes) -> list[FundPrice]:
    """Reads the sheet's (Excel date, price, currency) rows; raises ValueError on anything else."""
    rows = _rows(xlsx)
    header = rows[0] if rows else []
    if header[: len(_HEADER)] != _HEADER:
        msg = f"expected the columns {', '.join(_HEADER)}, found {', '.join(c or '(empty)' for c in header)}"
        raise ValueError(msg)
    prices = []
    for n, (serial, price, currency) in enumerate((row[: len(_HEADER)] for row in rows[1:]), start=2):
        msg = f"row {n} is not a date, price and currency: {serial!r}, {price!r}, {currency!r}"
        if serial is None or price is None or not currency:
            raise ValueError(msg)
        try:
            prices.append(FundPrice(isin=isin, day=_excel_date(serial), price=Decimal(price), currency=currency))
        except (InvalidOperation, ValueError) as e:
            raise ValueError(msg) from e
    return prices


def _rows(xlsx: bytes) -> list[list[str | None]]:
    """The cell texts of the sheet's first columns, row by row; None for an empty cell."""
    # S314: expat resolves no external entities and limits entity expansion, so ElementTree is safe here.
    with zipfile.ZipFile(BytesIO(xlsx)) as z:
        shared = []
        if _SHARED_STRINGS in z.namelist():
            root = ET.fromstring(z.read(_SHARED_STRINGS))  # noqa: S314 - see above
            shared = ["".join(t.text or "" for t in si.iter(f"{_NS}t")) for si in root.iter(f"{_NS}si")]
        sheet = ET.fromstring(z.read(_SHEET))  # noqa: S314 - see above
    rows = []
    for row in sheet.iter(f"{_NS}row"):
        cells: dict[str, str] = {}
        for cell in row.iter(f"{_NS}c"):
            column = (cell.get("r") or "").rstrip("0123456789")
            if cell.get("t") == "inlineStr":
                cells[column] = "".join(t.text or "" for t in cell.iter(f"{_NS}t"))
            elif (value := cell.find(f"{_NS}v")) is not None and value.text is not None:
                cells[column] = shared[int(value.text)] if cell.get("t") == "s" else value.text
        rows.append([cells.get(column) for column in _COLUMNS])
    return rows


def _excel_date(serial: str) -> date:
    days = Decimal(serial)
    if days != days.to_integral_value():
        msg = f"{serial} is not a whole day"
        raise ValueError(msg)
    return _EXCEL_EPOCH + timedelta(days=int(days))
