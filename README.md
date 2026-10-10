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
uv run inflation-station fetch-prices                # download fund prices from Conseq; keeps stored prices
uv run inflation-station fetch-fx                    # download CZK rates from ČNB for funds not priced in CZK
uv run inflation-station fetch-cpi                   # download ČSÚ's CPI and Eurostat's HICP, for the inflation hurdles
uv run inflation-station chart                       # write data/chart.html; open it in a browser
```

`fetch-prices` finds each fund's Conseq page in `src/inflation_station/conseq_funds.toml`. To add a fund, put its ISIN and the URL of its page on [conseq.cz](https://www.conseq.cz/investice/prehled-fondu) there. After fetching, it compares each Purchase's unit price from the export with Conseq's price on the trade date and warns when they are in different currencies or differ by more than 0.5 % of Conseq's price; the warning changes nothing and Conseq's price is what the chart uses.

`fetch-fx` downloads [ČNB](https://www.cnb.cz)'s daily rates for each currency a fund was bought in, a month per request, from the month of the first such Purchase to today. Re-runs request only months not stored yet, plus the latest stored month, in case it was fetched before it ended. The chart values those funds in CZK at the last rate published on or before each day.

`fetch-cpi` downloads [ČSÚ](https://csu.gov.cz)'s month-on-month CPI changes (the headline "míra inflace") and chains them into an index; re-runs keep the months already stored and continue the index from them. The chart then draws the **inflation hurdle**: what the money invested would need to be worth to keep its purchasing power, each Purchase grown by the index from its trade date. Each month's index sits on its first day, with constant daily growth in between. Months ČSÚ hasn't published yet are estimated at the last published month-on-month change and drawn dotted.

`fetch-cpi` also downloads [Eurostat](https://ec.europa.eu/eurostat)'s HICP for Czechia (`prc_hicp_minr`, 2015 = 100), the EU-harmonised measure, and the chart draws its hurdle as a second, dashed grey line, estimated the same way. Each index is stored on its own: if one download fails, the other is still saved, and the command exits non-zero naming the index that failed.
