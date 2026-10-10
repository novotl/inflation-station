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

## Usage

All data lives in `./data` (gitignored) unless you pass `--data-dir` or set `INFLATION_STATION_DATA_DIR`.

```sh
uv run inflation-station import data/jt_export.csv   # load a J&T transaction export; safe to re-run
```
