"""Write cash.pdf and holdings.pdf: a made-up INVESTIKA statement pair laid out like the real ones.

Usage: uv run python tests/fixtures/investika/make_pdfs.py <font.ttf>

The font must have Czech glyphs, e.g. DejaVuSans.ttf. Only the glyphs used are embedded.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF

HERE = Path(__file__).parent
# A fixed creation date, so re-running gives the same files.
CREATED = datetime(2026, 10, 11, tzinfo=UTC)
CONTRACT = "1234567890"
FUND = "INVESTIKA realitní fond, otevřený podílový fond - Třída CZK"
PAYMENT = "Odchozí platba z VÚ na investici"
DEPOSIT = "Investice klienta - vklad na VÚ"

# Datum, Popis, Specifický symbol, Typ, Částka; newest first, as in the real statement.
CASH_ROWS = [
    # A pending payment: ordered, but no units issued yet.
    ("01.10.2026", DEPOSIT, "", "Kredit", "5 000,00 CZK"),
    ("01.10.2026", PAYMENT, "", "Debet", "5 000,00 CZK"),
    ("10.09.2026 12:16:38", "Zaokrouhlení", "", "Debet", "1,09 CZK"),
    ("10.09.2026 11:02:49", f"{FUND}, Pravidelná investice", "", "Debet", "4 898,91 CZK"),
    ("10.09.2026 09:54:37", "Vstupní poplatek za pravidelnou investici", "", "Debet", "100,00 CZK"),
    ("03.08.2026", PAYMENT, "", "Debet", "5 000,00 CZK"),
    ("03.08.2026", DEPOSIT, "", "Kredit", "5 000,00 CZK"),
    ("19.04.2021", PAYMENT, "3030", "Debet", "10 200,00 CZK"),
    ("19.04.2021", DEPOSIT, "3030", "Kredit", "10 200,00 CZK"),
]
CASH_COLUMNS = (15, 50, 175, 205, 230)

# Each row's first line, then its second: the end of the fund name, the currencies and the settlement time.
HOLDINGS_ROWS = [
    (
        ("INVESTIKA realitní fond, otevřený", "CZ0008474830", "Vydání CP", "2783", "1,7603", "4 898,91"),
        ("31.08.2026", "10.09.2026", "03.08.2026"),
        "11:02:49",
    ),
    (
        ("INVESTIKA realitní fond, otevřený", "CZ0008474830", "Vydání CP", "7761", "1,2883", "9 998,50"),
        ("30.04.2021", "10.05.2021", "19.04.2021"),
        "16:21:05",
    ),
]
HOLDINGS_COLUMNS = (15, 68, 95, 118, 135, 152, 175, 200, 230)


def page(font: Path, title: str) -> FPDF:
    pdf = FPDF(orientation="landscape")
    pdf.add_font("Sans", fname=font)
    pdf.add_page()
    pdf.set_font("Sans", size=14)
    pdf.text(15, 15, title)
    pdf.set_font("Sans", size=8)
    pdf.text(10, 25, "Datum exportu:")
    pdf.text(40, 25, "11.10.2026")
    for y, (label, value) in enumerate(
        [("Číslo smlouvy:", CONTRACT), ("Investiční program:", f"{FUND} (CZK)")], start=0
    ):
        pdf.text(15, 35 + 12 * y, label)
        pdf.text(15, 40 + 12 * y, value)
    return pdf


def row(pdf: FPDF, y: float, columns: tuple[int, ...], cells: tuple[str, ...]) -> None:
    for x, cell in zip(columns, cells, strict=True):
        if cell:
            pdf.text(x, y, cell)


def cash(font: Path) -> FPDF:
    pdf = page(font, "Pohyby na peněžním účtu")
    row(pdf, 65, CASH_COLUMNS, ("Datum", "Popis", "Specifický symbol", "Typ", "Částka"))
    for i, cells in enumerate(CASH_ROWS):
        row(pdf, 75 + 8 * i, CASH_COLUMNS, cells)
    pdf.text(15, 200, "www.investika.cz")
    return pdf


def holdings(font: Path) -> FPDF:
    pdf = page(font, "Transakce na majetkovém účtu")
    row(pdf, 62, HOLDINGS_COLUMNS[2:5] + HOLDINGS_COLUMNS[6:], ("Typ", "Počet", "Cena /", "Datum", "Datum", "Datum"))
    row(
        pdf,
        66,
        HOLDINGS_COLUMNS,
        ("Název fondu", "ISIN", "transakce", "kusů", "kus", "Částka", "ceny", "vypořádání", "pokynu"),
    )
    for i, (first, dates, time) in enumerate(HOLDINGS_ROWS):
        y = 76 + 12 * i
        row(pdf, y, HOLDINGS_COLUMNS, first + dates)
        row(pdf, y + 4, HOLDINGS_COLUMNS, ("podílový fond - Třída CZK", "", "", "", "CZK", "CZK", "", time, ""))
    pdf.text(15, 200, "www.investika.cz")
    return pdf


def main() -> None:
    font = Path(sys.argv[1])
    for name, make in (("cash.pdf", cash), ("holdings.pdf", holdings)):
        pdf = make(font)
        pdf.set_creation_date(CREATED)
        pdf.output(str(HERE / name))


if __name__ == "__main__":
    main()
