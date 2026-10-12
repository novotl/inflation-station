# inflation-station

Track how your investments perform against inflation.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # create .venv and install dev dependencies
uv run pre-commit install      # enable git hooks
uv run pre-commit run --all-files
uv run pytest                  # tests + coverage report
```

### Database migrations

The schema is managed by [Alembic](https://alembic.sqlalchemy.org/); every command brings the database up to date before it runs. After changing the models in `src/inflation_station/store.py`, generate a migration and review it:

```sh
uv run alembic revision --autogenerate -m "describe the change"
```

## Usage

All data lives in the repo's gitignored `data/` directory unless you pass `--data-dir` or set `INFLATION_STATION_DATA_DIR`, either in the environment or in a `.env` file at the repo root (see `.env.example`).

```sh
uv run inflation-station import data/jt_export.csv   # load a J&T transaction export; safe to re-run
uv run inflation-station import data/investika_penezni.pdf data/investika_majetkovy.pdf   # load INVESTIKA statements
uv run inflation-station import data/portu.csv       # load a Portu transaction export; safe to re-run
uv run inflation-station fetch-prices                # download fund prices from Conseq; keeps stored prices
uv run inflation-station fetch-fx                    # download CZK rates from ČNB for funds and Cash not in CZK
uv run inflation-station fetch-cpi                   # download ČSÚ's CPI and Eurostat's HICP, for the inflation hurdles
uv run inflation-station chart                       # write data/chart.html; open it in a browser
```

`import` takes one or more files and recognises each from its content: a J&T or a [Portu](https://www.portu.cz) transaction export (CSV) by its header, an [INVESTIKA](https://www.investika.cz) statement (PDF) by its title. INVESTIKA only exports PDF statements, two per contract, and both must be given together: the cash statement (`Pohyby na peněžním účtu`) and the holdings statement (`Transakce na majetkovém účtu`) with the same `Číslo smlouvy`. Each issue of units (`Vydání CP`) becomes a Purchase dated by its price date (see [ADR 0001](docs/adr/0001-investika-trade-date-is-the-price-date.md)); the amount paid comes from the cash statement's payment on the issue's order date, and the fee is that payment less the issue's amount. Payments with no units issued yet are skipped until a later export has them. Any transaction type the import doesn't know, in either file, fails the import; if any file fails, nothing is imported.

Portu is a Managed Account: you deposit CZK and Portu decides what to buy, sell, hedge and charge, so its money invested is each Deposit (`Vklad z bankovního účtu`), counted in the amount invested and both inflation hurdles from its date (see [ADR 0002](docs/adr/0002-portu-money-invested-is-the-deposit.md)). Its buys (`Nákup`) and sells (`Prodej`) are not Purchases: they move the units held of each fund, which appear on the chart with the units they hold but nothing invested in them. Every row, including currency swaps and forwards (`Forex nákup`, `Forex prodej`) and monthly fees (`Poplatek`), moves the Account's Cash in its currency (`Měna`). The Account's value, and so the portfolio's, includes that Cash, so fees reduce it, and Cash that goes negative for a day (one leg of a currency swap settling a day before the other) counts as negative. The Account is the portfolio's name (`Název`), so a renamed portfolio is imported as a new Account (if Portu also renames it on past rows, those rows, Deposits included, are imported again under the new name). Exports hold the full history: a row is recognised by its date, type, symbol, amount and currency (counting exact repeats), so re-importing a later export adds only the new rows. Any other row type fails the import, naming it with the file and row. Portu's funds are exchange-traded and not on Conseq, so they show "no prices stored" for now.

`fetch-prices` finds each fund's Conseq page in `src/inflation_station/conseq_funds.toml`. To add a fund, put its ISIN and the URL of its page on [conseq.cz](https://www.conseq.cz/investice/prehled-fondu) there. After fetching, it compares each Purchase's unit price from the export with Conseq's price on the trade date and warns when they are in different currencies or differ by more than 0.5 % of Conseq's price; the warning changes nothing and Conseq's price is what the chart uses.

`fetch-fx` downloads [ČNB](https://www.cnb.cz)'s daily rates for each currency a fund was bought in or Portu holds Cash in, a month per request, from the month of the first such Purchase or Portu row to today. Re-runs request only months not stored yet, plus the latest stored month, in case it was fetched before it ended. The chart values those funds and that Cash in CZK at the last rate published on or before each day. Hovering a fund's line shows its CZK value, its value in the fund's own currency (left out for CZK funds) and the units held that day, e.g. `45,678.12 CZK (1,820.50 EUR) · 780.57 units`.

`fetch-cpi` downloads [ČSÚ](https://csu.gov.cz)'s month-on-month CPI changes (the headline "míra inflace") and chains them into an index; re-runs keep the months already stored and continue the index from them. The chart then draws the **inflation hurdle**: what the money invested would need to be worth to keep its purchasing power, each Purchase grown by the index from its trade date and each Portu Deposit from its date. Each month's index sits on its first day, with constant daily growth in between. Months ČSÚ hasn't published yet are estimated at the last published month-on-month change and drawn dotted.

`fetch-cpi` also downloads [Eurostat](https://ec.europa.eu/eurostat)'s HICP for Czechia (`prc_hicp_minr`, 2015 = 100), the EU-harmonised measure, and the chart draws its hurdle as a second, dashed line in the same colour, estimated the same way. Each index is stored on its own: if one download fails, the other is still saved, and the command exits non-zero naming the index that failed.

`chart` warns on stderr when a stored series is out of date, naming it and the date of its last point: a fund's prices or a currency's rates more than 5 business days old, or a price index whose last month is more than 2 months before the current one (both indices publish a month by the end of the next). A fund priced monthly, whose last two prices are more than 20 days apart, is judged like a price index: INVESTIKA publishes each month-end price about six weeks later, so on 11 October its prices still end on 31 August, and that is out of date only from November. The page shows the same warnings at the top. The chart is still written and the command still succeeds.

The page has three layouts of the same data, switched in its top bar (or with ←/→, or `?view=dashboard|relative|funds`):

- **Dashboard**: today's value, amount invested (fees included), gain and standing against each hurdle; a chart of the portfolio's value, amount invested and both hurdles; then a table of funds, a click on a row opening its chart.
- **Relative to inflation**: how far the value is above or below the ČSÚ CPI hurdle (real) and the amount invested (nominal), in %, for the portfolio and then for each fund on one scale. ČSÚ's estimated months are shaded.
- **Fund strip**: a tile per fund above one big chart: for the whole portfolio, Portu's Cash and each fund's value stacked, so the top edge is the portfolio value; for a fund, its own.

Funds (ISINs), Purchases and Portu holdings from every platform combined, are ordered by CZK value today, largest first. A fund's chart has, in CZK, its value, the amount invested in it (fees included) and both inflation hurdles, grown from that fund's Purchases only. A fund that can't be valued still appears, last, saying why, with the units held on its amount-invested hover. Value, amount invested and inflation each have one colour on every chart; the relative lines take the colour of what they're measured against.

The top bar switches between light and dark (following the system until chosen) and turns on private mode, which blurs every absolute amount and hides the CZK axes and hovers, leaving percentages readable; both choices are remembered in the browser. The page is one self-contained HTML file: plotly.js, its styles and scripts are inlined, and it loads nothing from the network.
