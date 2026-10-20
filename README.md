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

The schema is managed by [Alembic](https://alembic.sqlalchemy.org/); every command brings the database up to date before it runs. A database stored before the normalized schema (migrations `0001`–`0008`, squashed into today's `0001`) can't be upgraded: delete it, import your exports again and fetch prices, rates and price indices again. After changing the models in `src/inflation_station/store.py`, generate a migration and review it:

```sh
uv run alembic revision --autogenerate -m "describe the change"
```

## Usage

All data lives in the repo's gitignored `data/` directory unless you pass `--data-dir` or set `INFLATION_STATION_DATA_DIR`, either in the environment or in a `.env` file at the repo root (see `.env.example`).

```sh
uv run inflation-station import data/jt_export.csv   # load a J&T transaction export; safe to re-run
uv run inflation-station import data/investika_penezni.pdf data/investika_majetkovy.pdf   # load INVESTIKA statements
uv run inflation-station import data/portu.csv       # load a Portu transaction export; safe to re-run
uv run inflation-station fetch-prices                # download fund prices from Conseq and Yahoo Finance; keeps stored prices
uv run inflation-station fetch-fx                    # download CZK rates from ČNB for funds and Cash not in CZK
uv run inflation-station fetch-cpi                   # download ČSÚ's CPI and Eurostat's HICP, for the inflation hurdles
uv run inflation-station chart                       # write data/chart.html; open it in a browser
```

`import` takes one or more files and recognises each from its content: a J&T or a [Portu](https://www.portu.cz) transaction export (CSV) by its header, an [INVESTIKA](https://www.investika.cz) statement (PDF) by its title. INVESTIKA only exports PDF statements, two per Portfolio (a contract, numbered by its `Číslo smlouvy`), and both must be given together: the cash statement (`Pohyby na peněžním účtu`) and the holdings statement (`Transakce na majetkovém účtu`) with the same `Číslo smlouvy`. Each issue of units (`Vydání CP`) becomes a Purchase of the issue's amount (`Částka`), dated by its price date (see [ADR 0001](docs/adr/0001-investika-trade-date-is-the-price-date.md)), and a Fee of the rest of the cash statement's payment on the issue's order date: the entry fee and the rounding. Payments with no units issued yet are skipped until a later export has them. Any transaction type the import doesn't know, in either file, fails the import; if any file fails, nothing is imported.

A J&T row becomes a Purchase of the CZK that bought its units and, unless its fee (`Poplatek`) is zero, a Fee of that fee; a fee in any currency but CZK fails the import. A row whose units are priced in another currency (e.g. EUR) is paid for by a Conversion of that CZK into the trade's volume (`Objem (v měně obchodu)`), which is then the Purchase's amount. Each Fund bought in a J&T portfolio is a Portfolio of its own, named by the Fund. Each Deposit (`Vklad…`) goes to the Portfolio of the Purchase whose payment, fee included, it equals, traded within 7 days of it either way; a Deposit with no such Purchase (e.g. `Migrace…`) fails the import, and one in any currency but CZK isn't supported yet. A Fee is money invested, never part of any Value.

Portu is a Managed Portfolio: you deposit CZK and Portu decides what to buy, sell, hedge and charge, so its money invested is each Deposit (`Vklad z bankovního účtu`), counted in the amount invested and both inflation hurdles from its date (see [ADR 0002](docs/adr/0002-amount-invested-is-the-deposits-on-every-platform.md)). Its buys (`Nákup`) are Purchases and its sells (`Prodej`) Sales, but they move only the units held of each fund, which appear on the chart with the units they hold but nothing invested in them; the Portu Portfolio's own section has the amount invested and the hurdles. Each currency swap or forward leg sold (`Forex prodej`) is paired with the leg bought (`Forex nákup`) on the same day with the same detail (a currency pair, in either order, e.g. `CZK/EUR` and `EUR/CZK`, or the same swap's name) into one Conversion; a leg with no single other leg fails the import, naming its row. Every row, Conversions and monthly fees (`Poplatek`) included, moves the Portfolio's Cash in its currency (`Měna`). The Portfolio's Value, and so the Whole Portfolio's, includes that Cash, so fees reduce it, and Cash that goes negative for a day (one leg of a currency swap settling a day before the other) counts as negative. The Portfolio is identified by its name (`Název`), so a renamed portfolio is imported as a new Portfolio (if Portu also renames it on past rows, those rows, Deposits included, are imported again under the new name). Exports hold the full history: a row is recognised by its date, type, symbol, amount and currency (counting exact repeats), and a Conversion by its sell leg, so re-importing a later export adds only the new rows. Any other row type fails the import, naming it with the file and row. Portu's funds are exchange-traded and not on Conseq; their prices come from Yahoo Finance.

`fetch-prices` downloads the prices of every fund purchased or held, each from whichever of two hand-edited files lists its ISIN:

- `src/inflation_station/conseq_funds.toml`, for funds Conseq sells: the URL of the fund's page on [conseq.cz](https://www.conseq.cz/investice/prehled-fondu).
- `src/inflation_station/yahoo_funds.toml`, for exchange-traded funds: the fund's [Yahoo Finance](https://finance.yahoo.com) ticker, e.g. `SXR7.DE` (Xetra, in EUR) or `CSPX.L` (LSE, in USD). An ETF is listed on several exchanges, often in different currencies; pick the listing in the currency it was bought in. Yahoo's daily close is the price, up to yesterday: today's is left out, as the market may still be open.

A fund in neither file, or in both, fails the command, naming it. After fetching, it compares the unit price of each Purchase and Sale with the fetched price on its date and warns when they are in different currencies or differ by more than 0.5 % of the fetched price, naming where that price comes from; the warning changes nothing and the fetched price is what the chart uses.

`fetch-fx` downloads [ČNB](https://www.cnb.cz)'s daily rates for each currency other than CZK that any imported row is in, a month per request, from the month of the first such row to today. Re-runs request only months not stored yet, plus the latest stored month, in case it was fetched before it ended. The chart values those funds and that Cash in CZK at the last rate published on or before each day. Hovering a fund's line shows its CZK value, its value in the fund's own currency (left out for CZK funds) and the units held that day, e.g. `45,678.12 CZK (1,820.50 EUR) · 780.57 units`.

`fetch-cpi` downloads [ČSÚ](https://csu.gov.cz)'s month-on-month CPI changes (the headline "míra inflace") and chains them into an index; re-runs keep the months already stored and continue the index from them. The chart then draws the **inflation hurdle**: what the money invested would need to be worth to keep its purchasing power, each Purchase grown by the index from its trade date and each Portu Deposit from its date. Each month's index sits on its first day, with constant daily growth in between. Months ČSÚ hasn't published yet are estimated at the last published month-on-month change and drawn dotted.

`fetch-cpi` also downloads [Eurostat](https://ec.europa.eu/eurostat)'s HICP for Czechia (`prc_hicp_minr`, 2015 = 100), the EU-harmonised measure, and the chart draws its hurdle as a second, dashed line in the same colour, estimated the same way. Each index is stored on its own: if one download fails, the other is still saved, and the command exits non-zero naming the index that failed.

`chart` warns on stderr when a stored series is out of date, naming it and the date of its last point: a fund's prices or a currency's rates more than 5 business days old, or a price index whose last month is more than 2 months before the current one (both indices publish a month by the end of the next). A fund priced monthly, whose last two prices are more than 20 days apart, is judged like a price index: INVESTIKA publishes each month-end price about six weeks later, so on 11 October its prices still end on 31 August, and that is out of date only from November. The page shows the same warnings at the top. The chart is still written and the command still succeeds.

The page has three layouts of the same data, switched in its top bar (or with ←/→, or `?view=dashboard|relative|funds`):

- **Dashboard**: today's value, amount invested (fees included), gain and standing against each hurdle; a chart of the Whole Portfolio's value, amount invested and both hurdles; a section per Portfolio with the same figures and chart; then a table of funds, a click on a row opening its chart.
- **Relative to inflation**: how far the value is above or below the ČSÚ CPI hurdle (real) and the amount invested (nominal), in %, for the Whole Portfolio and then for each Portfolio and each fund on one scale. ČSÚ's estimated months are shaded.
- **Fund strip**: a tile per Portfolio and per fund above one big chart: for the Whole Portfolio, Portu's Cash and each fund's value stacked, so the top edge is the Whole Portfolio value; for a Portfolio or a fund, its own.

Each Portfolio, on every Platform, has a section headed `<Platform> · <Portfolio>` (e.g. `J&T Banka · FF - World Fund A-ACC-CZK`, `Portu · Moje portfolio`): its value, its amount invested (its Deposits, or without any its Purchases plus their Fees) and both inflation hurdles, grown from those alone. One with Deposits is valued at its Holdings plus its Cash, as in the Whole Portfolio: each left out when it can't be valued. A Portfolio with nothing in it valued has no value, saying whether its funds or its Cash are missing, and one partly valued names what its value leaves out.

Each fund section is a Holding: one fund in one Portfolio, so the same fund in two Portfolios has two sections, each naming its Portfolio. Portfolios, and Holdings, are ordered by CZK value today, largest first. A fund's chart has, in CZK, its value, the amount invested in it (fees included) and both inflation hurdles, grown from that Holding's Purchases only. A fund that can't be valued still appears, last, saying why, with the units held on its amount-invested hover. A Portu Holding has nothing invested in it (see [ADR 0002](docs/adr/0002-amount-invested-is-the-deposits-on-every-platform.md)), so it shows only its value and units held; its Portfolio carries the amount invested and the hurdles. Value, amount invested and inflation each have one colour on every chart; the relative lines take the colour of what they're measured against.

The top bar switches between light and dark (following the system until chosen) and turns on private mode, which blurs every absolute amount and hides the CZK axes and hovers, leaving percentages readable; both choices are remembered in the browser. The page is one self-contained HTML file: plotly.js, its styles and scripts are inlined, and it loads nothing from the network.
