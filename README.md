# inflation-station

Track how your investments perform against inflation.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # create .venv and install dev dependencies
uv run pre-commit install      # enable git hooks
uv run pre-commit run --all-files
uv run pytest                  # tests + coverage report
uv run inflation-station
```
