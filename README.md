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
uv run inflation-station chart                       # write data/chart.html; open it in a browser
```

`fetch-prices` finds each fund's Conseq page in `src/inflation_station/conseq_funds.toml`. To add a fund, put its ISIN and the URL of its page on [conseq.cz](https://www.conseq.cz/investice/prehled-fondu) there. Funds priced in EUR aren't valued on the chart yet. After fetching, it compares each Purchase's unit price from the export with Conseq's price on the trade date and warns when they are in different currencies or differ by more than 0.5 % of Conseq's price; the warning changes nothing and Conseq's price is what the chart uses.
