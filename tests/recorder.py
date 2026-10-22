"""URLs fetched and the fixtures recorded for them, shared by conftest and tests."""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CONSEQ = FIXTURES / "conseq"
CNB = FIXTURES / "cnb"
CSU = FIXTURES / "csu"
EUROSTAT = FIXTURES / "eurostat"
YAHOO = FIXTURES / "yahoo"
FUND_PAGE = "https://www.conseq.cz/investice/prehled-fondu/"
PRICE_HISTORY = "https://www.conseq.cz/Conseq/Pricehist.ashx?productid={}&culture=cs-CZ"
EUR_RATES = "https://api.cnb.cz/cnbapi/exrates/daily-currency-month?currency=EUR&yearMonth={}&lang=EN"
CPI_CSV = "https://data.csu.gov.cz/api/dotaz/v1/data/vybery/CEN0101HT02?format=CSV"
HICP_JSON = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
    "?geo=CZ&coicop18=TOTAL&unit=I15&format=JSON&lang=EN"
)
# Every daily close before 1 Jul 2021 (00:00 UTC), the tests' "today".
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1=0&period2=1625097600&interval=1d"
# The months of EUR rates recorded: from the first EUR Purchase in the J&T fixture to "today".
EUR_MONTHS = ("2021-05", "2021-06", "2021-07")
