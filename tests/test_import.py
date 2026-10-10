from pathlib import Path

import pytest

from inflation_station.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "jt_export.csv"


def test_import_reports_purchases_added(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data-dir", str(tmp_path), "import", str(EXPORT)]) == 0
    assert capsys.readouterr().out == "7 Purchases added, 0 already present.\n"


def test_reimporting_the_same_export_adds_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--data-dir", str(tmp_path), "import", str(EXPORT)])
    capsys.readouterr()

    assert main(["--data-dir", str(tmp_path), "import", str(EXPORT)]) == 0
    assert capsys.readouterr().out == "0 Purchases added, 7 already present.\n"


def test_importing_an_overlapping_export_adds_only_new_purchases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--data-dir", str(tmp_path), "import", str(EXPORT)])
    capsys.readouterr()

    assert main(["--data-dir", str(tmp_path), "import", str(FIXTURES / "jt_export_overlap.csv")]) == 0
    assert capsys.readouterr().out == "2 Purchases added, 3 already present.\n"


def test_unknown_movement_type_fails_naming_the_row_and_imports_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-dir", str(tmp_path), "import", str(FIXTURES / "jt_export_unknown_movement.csv")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "error: jt_export_unknown_movement.csv row 3 (ID pohybu 900109999): "
        "unknown movement type 'Zpětný odkup klienta (výběr)'\n"
    )

    # The file's valid Purchase row was not stored either.
    main(["--data-dir", str(tmp_path), "import", str(EXPORT)])
    assert capsys.readouterr().out == "7 Purchases added, 0 already present.\n"


@pytest.mark.parametrize(
    ("original", "broken", "error"),
    [
        (
            '"5,41"',
            '"5,4x1"',
            "jt_export.csv row 4 (ID pohybu 900100003): Počet ks '5,4x1' is not a number like '1 501,01'\n",
        ),
        (
            "00:00 15.06.2021",
            "15.06.2021",
            (
                "jt_export.csv row 4 (ID pohybu 900100003): "
                "Datum a čas zobchodování '15.06.2021' is not a date like '00:00 31.12.2021'\n"
            ),
        ),
        (
            '"-8 000,00";CZK;LU1756523376;;900200001',
            '"-8 000,00";EUR;LU1756523376;;900200001',
            "jt_export.csv row 4 (ID pohybu 900100003): payment currency is 'EUR', expected 'CZK'\n",
        ),
        ("ID pohybu", "ID", "jt_export.csv is not a J&T export: missing columns ID pohybu\n"),
    ],
)
def test_malformed_export_fails_naming_the_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], original: str, broken: str, error: str
) -> None:
    export = tmp_path / "jt_export.csv"
    export.write_text(EXPORT.read_text(encoding="utf-8").replace(original, broken, 1), encoding="utf-8")

    assert main(["--data-dir", str(tmp_path), "import", str(export)]) == 1
    assert capsys.readouterr().err == f"error: {error}"


def test_missing_export_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data-dir", str(tmp_path), "import", str(tmp_path / "nope.csv")]) == 1
    assert capsys.readouterr().err.startswith(f"error: cannot read {tmp_path / 'nope.csv'}: ")


def test_data_dir_can_be_set_by_env_var(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INFLATION_STATION_DATA_DIR", str(tmp_path / "from-env"))
    main(["import", str(EXPORT)])
    capsys.readouterr()

    main(["--data-dir", str(tmp_path / "from-env"), "import", str(EXPORT)])
    assert capsys.readouterr().out == "0 Purchases added, 7 already present.\n"


def test_data_dir_option_overrides_env_var(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INFLATION_STATION_DATA_DIR", str(tmp_path / "from-env"))
    main(["--data-dir", str(tmp_path / "from-option"), "import", str(EXPORT)])
    capsys.readouterr()

    main(["import", str(EXPORT)])
    assert capsys.readouterr().out == "7 Purchases added, 0 already present.\n"


def test_data_dir_defaults_to_data_in_working_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INFLATION_STATION_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    main(["import", str(EXPORT)])
    capsys.readouterr()

    main(["--data-dir", str(tmp_path / "data"), "import", str(EXPORT)])
    assert capsys.readouterr().out == "0 Purchases added, 7 already present.\n"
