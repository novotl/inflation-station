from typing import TYPE_CHECKING

from inflation_station import main

if TYPE_CHECKING:
    import pytest


def test_main_prints_greeting(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    assert capsys.readouterr().out == "Hello from inflation-station!\n"
