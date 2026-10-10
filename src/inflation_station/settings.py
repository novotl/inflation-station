from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The tool runs from its checkout (`uv run`), so .env and data/ are anchored at the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration from INFLATION_STATION_* environment variables, else the repo's .env, else defaults."""

    model_config = SettingsConfigDict(env_prefix="INFLATION_STATION_", env_file=REPO_ROOT / ".env")

    data_dir: Path = REPO_ROOT / "data"
