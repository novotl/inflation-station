import time
from datetime import UTC, datetime

import pytest

from inflation_station import clock


@pytest.mark.parametrize("zone", ["Etc/GMT-14", "Etc/GMT+12"])  # UTC+14 and UTC-12: at any instant, one is off by a day
def test_today_is_the_utc_date_whatever_the_local_time_zone(monkeypatch: pytest.MonkeyPatch, zone: str) -> None:
    monkeypatch.setenv("TZ", zone)
    time.tzset()
    try:
        assert clock.today() == datetime.now(UTC).date()
    finally:
        monkeypatch.undo()
        time.tzset()
