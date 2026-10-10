from datetime import date

from inflation_station.cnb import months_to_fetch


def test_a_first_purchase_early_in_january_starts_in_january_itself() -> None:
    assert months_to_fetch(date(2022, 1, 3), today=date(2022, 2, 10), stored=[]) == [
        date(2022, 1, 1),
        date(2022, 2, 1),
    ]


def test_months_run_from_december_into_january() -> None:
    assert months_to_fetch(date(2021, 11, 20), today=date(2022, 1, 5), stored=[]) == [
        date(2021, 11, 1),
        date(2021, 12, 1),
        date(2022, 1, 1),
    ]


def test_with_rates_stored_only_the_latest_stored_month_and_later_are_fetched() -> None:
    stored = [date(2021, 5, 18), date(2021, 5, 31), date(2021, 6, 1), date(2021, 6, 15)]

    assert months_to_fetch(date(2021, 5, 18), today=date(2021, 8, 2), stored=stored) == [
        date(2021, 6, 1),
        date(2021, 7, 1),
        date(2021, 8, 1),
    ]
