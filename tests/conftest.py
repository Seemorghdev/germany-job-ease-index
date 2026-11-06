"""Shared fixtures: small synthetic workbooks shaped like the real BA and Destatis files."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

Rows = Sequence[Sequence[object]]


def write_xlsx(path: Path, sheets: dict[str, Rows]) -> Path:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(list(row))
    workbook.save(path)
    return path


def zip_one(path: Path, inner_name: str, payload: bytes) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inner_name, payload)
    path.write_bytes(buffer.getvalue())
    return path


# Months in the synthetic BA issue: June to December 2026, reporting month October.
# November and December are zero, as in the real issues.
BA_MONTHS = [datetime(2026, m, 1) for m in range(6, 13)]


def _ba_row(label: str, june_to_october: Sequence[object]) -> list[object]:
    """Label in column A, a yearly average in B, then one column per month from C."""
    return [label, 1234.5, *june_to_october, 0, 0]


@pytest.fixture
def ba_rows() -> list[list[object]]:
    return [
        ["Bestand an Arbeitslosen - Insgesamt"],
        [],
        ["Gesamt", "Jahresdurch-schnitt", *BA_MONTHS],
        ["Region", 2026, *range(1, len(BA_MONTHS) + 1)],
        ["Deutschland", None, 2_900_000, 2_910_000, 2_920_000, 2_930_000, 2_950_000, 0, 0],
        _ba_row("11000 Berlin, Stadt", [220_000, 221_000, 222_000, 223_000, 223_254]),
        _ba_row("05515 Münster, Stadt", [9_000, 9_010, 8_990, 8_970, 8_957]),
        _ba_row("09161 Ingolstadt, Stadt", [4_100, 4_120, 4_150, 4_170, "4.180"]),
        _ba_row("09176 Eichstätt", [2_000, 2_050, 2_080, 2_100, 2_104.0]),
        _ba_row("09184 München", [7_500, "*", None, 7_480, 7_503]),
    ]


@pytest.fixture
def make_ba_zip(tmp_path: Path) -> Callable[[list[list[object]]], Path]:
    def build(rows: list[list[object]]) -> Path:
        inner = write_xlsx(tmp_path / "inner.xlsx", {"Übersicht_Kreise": rows})
        return zip_one(tmp_path / "ba.zip", "202610_Heft_Arbeitslose.xlsx", inner.read_bytes())

    return build


@pytest.fixture
def gvisys_file(tmp_path: Path) -> Path:
    header = [
        "Satzart",
        "Textkennzeichen",
        "Land",
        "RB",
        "Kreis",
        "VB",
        "Gem",
        "Name",
        "Fläche",
        "Bev",
    ]
    rows: list[list[object]] = [
        ["Gemeindeverzeichnis", None, None, None, None, None, None, None, None, None],
        header,
        [10, None, "11", None, None, None, None, "Berlin", None, None],
        [40, 41, "11", "0", "00", None, None, "Berlin, Stadt", None, None],
        [60, 61, "11", "0", "00", "0000", "000", "Berlin, Stadt", 891.12, 3_700_000],
        [40, 41, 9, 1, 62, None, None, "München, Landeshauptstadt", None, None],
        [60, 61, 9, 1, 62, "0000", 0, "München, Landeshauptstadt", "310,7", 1_510_000],
        [40, 44, "09", "1", "84", None, None, "München", None, None],
        [60, 64, "09", "1", "84", "0113", "118", "Unterhaching", 10.5, 26_000],
        [60, 64, "09", "1", "84", "0113", "137", "Garching b.München", 28.2, 19_000],
        # Unpopulated area outside any district (GV-ISys lists coastal waters like this).
        [60, 64, "13", "0", "00", "0000", "000", "Küstengewässer", 1500.0, 0],
    ]
    return write_xlsx(tmp_path / "gvisys.xlsx", {"Onlineprodukt_Gemeinden": rows})
