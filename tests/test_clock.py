import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from inflation_station import clock

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def fixed_today() -> None:
    """Overrides conftest's pinned "today": this module tests the real clock."""


@pytest.fixture(params=["Etc/GMT-14", "Etc/GMT+12"])  # UTC+14 and UTC-12: at any instant, one is off by a day
def local_time_zone(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[None]:
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("local_time_zone")
def test_today_is_the_utc_date_whatever_the_local_time_zone() -> None:
    assert clock.today() == datetime.now(UTC).date()
