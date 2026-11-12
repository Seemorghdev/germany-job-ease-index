from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

import pytest

from conftest import write_xlsx
from jobease.sources import ba_occupations
from jobease.sources.ba_occupations import OccupationValue
from jobease.sources.xlsx import WorkbookError

OCT = date(2026, 10, 1)
OCT_BEFORE = date(2025, 10, 1)
WHEN = datetime(2026, 10, 15)
BEFORE = datetime(2025, 10, 15)
REGIONS = [
    "Deutschland",
    "Westdeutschland",
    "Ostdeutschland",
    "01 Schleswig-Holstein",
    "02 Hamburg",
    "03 Niedersachsen",
    "04 Bremen",
    "05 Nordrhein-Westfalen",
    "06 Hessen",
    "07 Rheinland-Pfalz",
    "08 Baden-Württemberg",
    "09 Bayern",
    "10 Saarland",
    "11 Berlin",
    "12 Brandenburg",
    "13 Mecklenburg-Vorpommern",
    "14 Sachsen",
    "15 Sachsen-Anhalt",
    "16 Thüringen",
]
Rows = list[list[object]]


def _header(region: str, when: datetime = WHEN, before: datetime = BEFORE) -> Rows:
    """The 15 rows above the data, as in the BA's overview sheets."""
    pair: list[object] = [when, before, "absolut", "in %"]
    return [
        [None] * 18 + ["Arbeitsmarktstatistik"],
        [],
        ["Arbeitsmarktdaten nach Zielberufen: Arbeitslose, Arbeitsuchende und Arbeitsstellen"],
        ["Übersicht"],
        ["Ausgewiesenes Anforderungsniveau: Helfer, Fachkraft, Spezialist, Experte"],
        [region],
        [when],
        [],
        ["Berufe nach der Klassifikation der Berufe 2010 (KldB 2010)"],
        [None, "Aktuelle Hinweise beachten", "in Blatt III"],
        [
            "Berufsbereich",
            None,
            None,
            "Arbeitslose",
            *[None] * 3,
            "Arbeitsuchende 1)",
            *[None] * 3,
            "Gemeldete Arbeitsstellen",
        ],
        [
            "Berufshauptgruppe",
            None,
            "Anfor-",
            "Bestand",
            *[None] * 7,
            "Bestand",
            *[None] * 3,
            "Zugang gleitende Jahressumme",
        ],
        ["Berufsgruppe", None, "derungs-", *[when, None, "Veränderung ", None] * 4],
        [None, None, "niveau", *pair * 4],
        [None, None, None, *range(1, 17)],
    ]


def _row(code: object, label: object, level: str, *values: object) -> list[object]:
    """Eight values: unemployed and the year before, then job seekers, vacancies, inflow."""
    u, u0, j, j0, v, v0, z, z0 = values
    return [code, label, level, u, u0, 0, 0, j, j0, 0, 0, v, v0, 0, 0, z, z0, 0, 0]


def _data() -> Rows:
    return [
        _row("Insgesamt", None, "Gesamt", 1000, 990, 1500, 1480, 300, 280, 700, 650),
        _row(None, None, "   Helfer", 500, 510, 700, 720, 40, 45, 90, 95),
        _row(None, None, "   Fachkraft", 300, 290, 450, 440, 180, 160, 400, 370),
        _row(None, None, "   Spezialist", 80, 70, 120, 110, 50, 45, 120, 110),
        _row(None, None, "   Experte", 70, 60, 110, 100, 30, 30, 90, 75),
        _row(None, None, "keine Angabe", 50, 60, 120, 110, "-", "-", None, None),
        _row("11", "Land-, Tier-, Forstwirtschaftsberufe", "Gesamt", 40, 41, 60, 61, 9, 8, 20, 21),
        _row(None, None, "Helfer", 30, 31, 45, 46, 4, "* ", 9, 10),
        _row(None, None, "Fachkraft", 10, 10, 15, 15, 5, 5, 11, 11),
        _row(114, "Fischwirtschaft", "Gesamt", 5, 4, 7, 6, "- ", "- ", "* ", 3),
        _row(None, None, "Fachkraft", 5, 4, 7, 6, "- ", "- ", "* ", 3),
        ["1) Arbeitsuchende einschließlich Arbeitsloser"],
    ]


def _sheet(region: str, data: Rows | None = None, **header: datetime) -> Rows:
    return _header(region, **header) + (data if data is not None else _data())


@pytest.fixture
def make_workbook(tmp_path: Path) -> Callable[..., Path]:
    def build(sheets: dict[str, Rows] | None = None) -> Path:
        if sheets is None:
            sheets = {f"1.{i}": _sheet(r) for i, r in enumerate(REGIONS, start=1)}
        workbook = {"Deckblatt": [["Arbeitsmarkt nach Berufen"]], **sheets, "2.1": [["x"]]}
        return write_xlsx(tmp_path / "berufe.xlsx", workbook)

    return build


def _find(rows: Sequence[OccupationValue], **match: object) -> OccupationValue:
    found = [r for r in rows if all(getattr(r, k) == v for k, v in match.items())]
    assert len(found) == 1, match
    return found[0]


def test_reads_every_region_month_and_measure(make_workbook: Callable[..., Path]) -> None:
    result = ba_occupations.parse_workbook(make_workbook())
    assert result.vintage == OCT
    assert set(result.regions) == {"DE", "W", "O", *(f"{n:02d}" for n in range(1, 17))}
    germany = [r for r in result.rows if r.region_code == "DE"]
    # 11 data rows × 4 measures × 2 months
    assert len(germany) == 11 * 4 * 2
    helfer = _find(
        germany, occupation_code="total", skill_level="helfer", measure="vacancies", period=OCT
    )
    assert (helfer.value, helfer.value_status) == (40, "value")
    before = _find(
        germany,
        occupation_code="total",
        skill_level="helfer",
        measure="unemployed",
        period=OCT_BEFORE,
    )
    assert before.value == 510
    land = _find(
        result.rows,
        region_code="08",
        occupation_code="total",
        skill_level="total",
        measure="unemployed",
        period=OCT,
    )
    assert land.region_name == "Baden-Württemberg"


def test_the_code_on_the_gesamt_row_applies_to_the_level_rows_below(
    make_workbook: Callable[..., Path],
) -> None:
    rows = ba_occupations.parse_workbook(make_workbook()).rows
    fachkraft = _find(
        rows,
        region_code="DE",
        occupation_code="11",
        skill_level="fachkraft",
        measure="unemployed",
        period=OCT,
    )
    assert fachkraft.value == 10
    assert fachkraft.occupation_label == "Land-, Tier-, Forstwirtschaftsberufe"
    assert fachkraft.occupation_digits == 2
    fish = _find(
        rows,
        region_code="DE",
        occupation_code="114",
        skill_level="fachkraft",
        measure="unemployed",
        period=OCT,
    )
    assert (fish.occupation_digits, fish.value) == (3, 5)  # an int code cell works too


def test_a_dash_is_zero_and_a_star_is_unknown(make_workbook: Callable[..., Path]) -> None:
    rows = ba_occupations.parse_workbook(make_workbook()).rows
    none_open = _find(
        rows,
        region_code="DE",
        occupation_code="114",
        skill_level="total",
        measure="vacancies",
        period=OCT,
    )
    assert (none_open.value, none_open.value_status) == (0, "zero")
    hidden = _find(
        rows,
        region_code="DE",
        occupation_code="11",
        skill_level="helfer",
        measure="vacancies",
        period=OCT_BEFORE,
    )
    assert (hidden.value, hidden.value_status) == (None, "suppressed")
    blank = _find(
        rows,
        region_code="DE",
        occupation_code="total",
        skill_level="unknown",
        measure="vacancy_inflow_12m",
        period=OCT,
    )
    assert (blank.value, blank.value_status) == (None, "empty")


def test_the_footnote_ends_the_table(make_workbook: Callable[..., Path]) -> None:
    rows = ba_occupations.parse_workbook(make_workbook()).rows
    assert max(r.row_number for r in rows) == 15 + 11


def test_a_missing_region_fails(make_workbook: Callable[..., Path]) -> None:
    sheets = {f"1.{i}": _sheet(r) for i, r in enumerate(REGIONS[:-1], start=1)}
    with pytest.raises(WorkbookError, match=r"missing \['16'\]"):
        ba_occupations.parse_workbook(make_workbook(sheets))


def test_a_region_twice_fails(make_workbook: Callable[..., Path]) -> None:
    sheets = {f"1.{i}": _sheet(r) for i, r in enumerate(REGIONS, start=1)}
    sheets["1.19"] = _sheet("15 Sachsen-Anhalt")
    with pytest.raises(WorkbookError, match="region 15 is in both"):
        ba_occupations.parse_workbook(make_workbook(sheets))


def test_sheets_from_different_months_fail(make_workbook: Callable[..., Path]) -> None:
    sheets = {f"1.{i}": _sheet(r) for i, r in enumerate(REGIONS, start=1)}
    sheets["1.5"] = _sheet("02 Hamburg", when=datetime(2026, 9, 15), before=datetime(2025, 9, 15))
    with pytest.raises(WorkbookError, match="disagree on the month"):
        ba_occupations.parse_workbook(make_workbook(sheets))


def test_a_shifted_column_fails(make_workbook: Callable[..., Path]) -> None:
    sheet = _sheet("Deutschland")
    sheet[10] = [None, *sheet[10]]  # the measure labels moved one column right
    with pytest.raises(WorkbookError, match="no 'Arbeitslose' header"):
        ba_occupations.parse_sheet("1.1", sheet)


def test_a_wrong_year_before_column_fails() -> None:
    sheet = _sheet("Deutschland", before=datetime(2024, 10, 15))
    with pytest.raises(WorkbookError, match="expected 2026-10-01 and 2025-10-01"):
        ba_occupations.parse_sheet("1.1", sheet)


def test_no_numbered_row_fails() -> None:
    sheet = _sheet("Deutschland")
    del sheet[14]
    with pytest.raises(WorkbookError, match="no numbered header row"):
        ba_occupations.parse_sheet("1.1", sheet)


def test_an_unknown_skill_level_fails() -> None:
    data = _data()
    data[2][2] = "Fachkräfte"
    with pytest.raises(WorkbookError, match="unknown skill level"):
        ba_occupations.parse_sheet("1.1", _sheet("Deutschland", data))


def test_a_level_twice_under_one_code_fails() -> None:
    data = _data()
    data.insert(3, list(data[2]))
    with pytest.raises(WorkbookError, match="total fachkraft appears twice"):
        ba_occupations.parse_sheet("1.1", _sheet("Deutschland", data))


def test_a_value_that_isnt_a_count_fails_with_its_place() -> None:
    data = _data()
    data[1][3] = "12,5"
    with pytest.raises(WorkbookError, match=r"row 17 \(total helfer, unemployed\)"):
        ba_occupations.parse_sheet("1.1", _sheet("Deutschland", data))
