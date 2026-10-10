from datetime import date


def today() -> date:
    """The local date. Tests replace this function to pin "today"."""
    return date.today()  # noqa: DTZ011 - "today" is the user's calendar day, in their local time zone
