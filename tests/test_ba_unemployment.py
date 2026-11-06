from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from conftest import BA_MONTHS
from jobease.sources import ba_unemployment
from jobease.sources.ba_unemployment import parse_month
from jobease.sources.xlsx import WorkbookError

OCT = date(2026, 10, 1)
CONTROLS = {
    (OCT, "11000"): 223_254,
    (OCT, "05515"): 8_957,
    (OCT, "09161"): 4_180,
    (OCT, "09176"): 2_104,
}

MakeZip = Callable[[list[list[object]]], Path]


def _parse(path: Path, sheet_name: str = "Übersicht_Kreise") -> ba_unemployment.ParseResult:
    return ba_unemployment.parse_workbook(
        path, sheet_name=sheet_name, label_column="A", inner_suffix="_Arbeitslose.xlsx"
    )


def _value(result: ba_unemployment.ParseResult, period: date, code: str) -> int | None:
    return next(r.unemployed for r in result.rows if r.period == period and r.district_code == code)


def test_reads_every_month_up_to_the_reporting_month(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    result = _parse(make_ba_zip(ba_rows))
    assert result.vintage == OCT
    assert result.months == tuple(date(2026, m, 1) for m in range(6, 11))  # Nov, Dec dropped
    assert {r.district_code for r in result.rows} == {"11000", "05515", "09161", "09176", "09184"}
    assert len(result.rows) == 5 * 5
    assert _value(result, OCT, "09161") == 4_180  # "4.180" with a thousands dot
    assert _value(result, date(2026, 6, 1), "11000") == 220_000


def test_records_why_a_value_is_missing(make_ba_zip: MakeZip, ba_rows: list[list[object]]) -> None:
    result = _parse(make_ba_zip(ba_rows))
    munich = {r.period.month: r for r in result.rows if r.district_code == "09184"}
    assert (munich[7].unemployed, munich[7].value_status) == (None, "suppressed")
    assert (munich[8].unemployed, munich[8].value_status) == (None, "empty")
    assert munich[10].value_status == "value"
    assert result.count("suppressed") == 1


def test_a_zero_inside_the_reported_months_is_kept_as_zero_status(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    ba_rows[6][2] = 0  # Münster, June
    result = _parse(make_ba_zip(ba_rows))
    june = next(r for r in result.rows if r.district_code == "05515" and r.period.month == 6)
    assert (june.unemployed, june.value_status) == (None, "zero")


def test_vintage_follows_the_data_not_the_header(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    for row in ba_rows[5:]:
        row[6] = 0  # nobody reported October yet
    assert _parse(make_ba_zip(ba_rows)).vintage == date(2026, 9, 1)


def test_suppressed_symbol_after_the_reporting_month_fails(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    ba_rows[5][7] = "*"  # Berlin, November
    with pytest.raises(WorkbookError, match="after the reporting month"):
        _parse(make_ba_zip(ba_rows))


def test_controls_pass_for_matching_workbook(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    result = _parse(make_ba_zip(ba_rows))
    assert ba_unemployment.check_controls(result.rows, CONTROLS) == 4


def test_controls_catch_a_shifted_month(make_ba_zip: MakeZip, ba_rows: list[list[object]]) -> None:
    ba_rows[2][6], ba_rows[2][5] = BA_MONTHS[3], BA_MONTHS[4]  # September/October swapped
    result = _parse(make_ba_zip(ba_rows))
    with pytest.raises(ba_unemployment.ControlMismatchError, match="11000"):
        ba_unemployment.check_controls(result.rows, CONTROLS)


def test_controls_outside_the_covered_months_are_skipped(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    result = _parse(make_ba_zip(ba_rows))
    assert ba_unemployment.check_controls(result.rows, {(date(2020, 1, 1), "11000"): 1}) == 0


def test_duplicate_district_fails(make_ba_zip: MakeZip, ba_rows: list[list[object]]) -> None:
    ba_rows.append(list(ba_rows[5]))
    with pytest.raises(WorkbookError, match="twice"):
        _parse(make_ba_zip(ba_rows))


def test_non_count_value_fails_loudly(make_ba_zip: MakeZip, ba_rows: list[list[object]]) -> None:
    ba_rows[6][4] = "10,4"  # a rate, not a count
    with pytest.raises(WorkbookError, match=r"05515.*2026-08"):
        _parse(make_ba_zip(ba_rows))


def test_sheet_without_month_header_fails(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    del ba_rows[2]
    with pytest.raises(WorkbookError, match="month cells"):
        _parse(make_ba_zip(ba_rows))


def test_missing_sheet_lists_available_sheets(
    make_ba_zip: MakeZip, ba_rows: list[list[object]]
) -> None:
    with pytest.raises(WorkbookError, match="available"):
        _parse(make_ba_zip(ba_rows), sheet_name="Nope")


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Oktober 2026", date(2026, 10, 1)),
        ("Mär 2008", date(2008, 3, 1)),
        ("Dez. 2015", date(2015, 12, 1)),
        ("10/2026", date(2026, 10, 1)),
        ("Jahresdurch-schnitt", None),
        ("Gleitender JD November 2025 - Oktober 2026", None),
        ("13/2026", None),
        (2026, None),
    ],
)
def test_parse_month(cell: object, expected: date | None) -> None:
    assert parse_month(cell) == expected
