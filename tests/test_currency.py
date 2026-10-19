import pytest

from inflation_station import currency


@pytest.mark.parametrize("code", ["CZK", "EUR", "USD", "HUF", "XAU"])
def test_an_iso_4217_code_is_a_currency(code: str) -> None:
    assert currency.code(code) == code


@pytest.mark.parametrize("text", ["", "czk", "CZ", "CZKK", "ABC", "Kč", " CZK"])
def test_anything_else_is_rejected_naming_it(text: str) -> None:
    with pytest.raises(ValueError, match=f"{text!r} is not an ISO 4217 currency code"):
        currency.code(text)
