from datetime import UTC, date, datetime


def today() -> date:
    """The UTC date, never the local one, so results don't depend on the machine's time zone.

    Tests replace this function to pin "today".
    """
    return datetime.now(UTC).date()
