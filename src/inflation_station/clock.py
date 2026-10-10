from datetime import UTC, date, datetime


def today() -> date:
    """The UTC date, never the local one. Tests replace this function to pin "today"."""
    return datetime.now(UTC).date()
