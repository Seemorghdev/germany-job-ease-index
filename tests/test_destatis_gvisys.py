from __future__ import annotations

from pathlib import Path

import pytest

from conftest import write_xlsx
from jobease.config import GVISYS_DEFAULT_COLUMNS
from jobease.sources import destatis_gvisys
from jobease.sources.xlsx import WorkbookError


def test_parses_municipalities_and_districts(gvisys_file: Path) -> None:
    result = destatis_gvisys.parse_workbook(
        gvisys_file, sheet_name=None, columns=GVISYS_DEFAULT_COLUMNS
    )
    municipalities = {m.ags: m for m in result.municipalities}
    districts = {d.district_code: d for d in result.districts}

    assert set(municipalities) == {"11000000", "09162000", "09184118", "09184137"}
    assert set(districts) == {"11000", "09162", "09184"}
    assert municipalities["09162000"].area_km2 == pytest.approx(310.7)  # German comma
    assert municipalities["11000000"].population == 3_700_000
    assert [m.ags for m in result.excluded] == ["13000000"]


def test_populated_municipality_outside_any_district_fails(tmp_path: Path) -> None:
    rows: list[list[object]] = [
        [40, 41, "11", "0", "00", None, None, "Berlin, Stadt", None, None],
        [60, 61, "11", "0", "00", "0000", "000", "Berlin, Stadt", 891.12, 3_700_000],
        [60, 61, "13", "0", "00", "0000", "001", "Somewhere", 10.0, 500],
    ]
    path = write_xlsx(tmp_path / "bad.xlsx", {"Gemeinden": rows})
    with pytest.raises(WorkbookError, match="Somewhere"):
        destatis_gvisys.parse_workbook(path, sheet_name=None, columns=GVISYS_DEFAULT_COLUMNS)


def test_city_and_landkreis_with_the_same_name_stay_apart(gvisys_file: Path) -> None:
    """The v4 bug: 'München' matched the Landkreis. Codes keep them apart."""
    result = destatis_gvisys.parse_workbook(
        gvisys_file, sheet_name=None, columns=GVISYS_DEFAULT_COLUMNS
    )
    districts = {d.district_code: d for d in result.districts}
    city = next(m for m in result.municipalities if m.name.startswith("München"))
    assert city.ags[:5] == "09162"
    assert districts["09162"].type_code == "41"
    assert districts["09184"].type_code == "44"


def test_numeric_codes_are_zero_padded(gvisys_file: Path) -> None:
    result = destatis_gvisys.parse_workbook(
        gvisys_file, sheet_name=None, columns=GVISYS_DEFAULT_COLUMNS
    )
    assert "09162000" in {m.ags for m in result.municipalities}  # land=9, gem=0 as numbers


def test_wrong_column_mapping_fails(gvisys_file: Path) -> None:
    columns = {**GVISYS_DEFAULT_COLUMNS, "record_type": "J"}
    with pytest.raises(WorkbookError):
        destatis_gvisys.parse_workbook(gvisys_file, sheet_name=None, columns=columns)


@pytest.mark.parametrize(
    ("official", "expected"),
    [
        ("München, Landeshauptstadt", "München"),
        ("Halle (Saale), Stadt", "Halle (Saale)"),
        ("Frankfurt am Main, Stadt", "Frankfurt am Main"),
        ("Unterhaching", "Unterhaching"),
    ],
)
def test_search_name(official: str, expected: str) -> None:
    assert destatis_gvisys.search_name(official) == expected
