"""BA "Arbeitslose nach Ländern und Kreisen": unemployed people per district, by month.

Each monthly issue holds a run of months (in October 2026: January 2025 to December 2026),
one column per month, with a header row of month dates. Months after the reporting month
are present but zero. The reporting month (the workbook's *vintage*) is therefore the
latest month with any non-zero value, and later months are dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from openpyxl.utils import column_index_from_string

from jobease.sources import xlsx
from jobease.sources.numbers import parse_count

_CODE_AND_NAME = re.compile(r"^\s*(\d{5})\s+(\S.*?)\s*$")

# A header row has at least this many month cells. Real issues have 22-24.
MIN_MONTH_COLUMNS = 6

_GERMAN_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("januar", "jan"),
            ("februar", "feb"),
            ("märz", "mär", "maerz", "mrz"),
            ("april", "apr"),
            ("mai",),
            ("juni", "jun"),
            ("juli", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("oktober", "okt"),
            ("november", "nov"),
            ("dezember", "dez"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_TEXT = re.compile(r"^\s*([A-Za-zÄÖÜäöü]+)\.?\s+(\d{4})\s*$")
_MONTH_NUMERIC = re.compile(r"^\s*(\d{1,2})[./](\d{4})\s*$")

ValueStatus = Literal["value", "suppressed", "empty", "zero"]


@dataclass(frozen=True)
class MonthlyUnemployment:
    period: date
    district_code: str
    district_label: str
    unemployed: int | None
    value_status: ValueStatus


@dataclass(frozen=True)
class ParseResult:
    vintage: date
    months: tuple[date, ...]
    rows: tuple[MonthlyUnemployment, ...]

    def count(self, status: ValueStatus) -> int:
        return sum(1 for r in self.rows if r.value_status == status)


class ControlMismatchError(ValueError):
    """The workbook doesn't reproduce figures the BA published itself."""


def parse_month(value: object) -> date | None:
    """A header cell as the first of its month, or ``None`` if it isn't a month."""
    if isinstance(value, datetime | date):
        return date(value.year, value.month, 1)
    if not isinstance(value, str):
        return None
    if match := _MONTH_TEXT.match(value):
        month = _GERMAN_MONTHS.get(match.group(1).lower())
        return date(int(match.group(2)), month, 1) if month else None
    if match := _MONTH_NUMERIC.match(value):
        month = int(match.group(1))
        return date(int(match.group(2)), month, 1) if 1 <= month <= 12 else None
    return None


def _month_columns(row: tuple[object, ...]) -> dict[int, date]:
    columns = {i: m for i, cell in enumerate(row) if (m := parse_month(cell)) is not None}
    return columns if len(columns) >= MIN_MONTH_COLUMNS else {}


def _status(raw: object, count: int | None) -> ValueStatus:
    if count is None:
        return "empty" if raw is None or str(raw).strip() == "" else "suppressed"
    return "zero" if count == 0 else "value"


def parse_workbook(
    path: Path,
    *,
    sheet_name: str,
    label_column: str,
    inner_suffix: str | None = None,
) -> ParseResult:
    label_index = column_index_from_string(label_column) - 1
    months: dict[int, date] = {}
    header_row = 0
    parsed: dict[str, tuple[str, dict[date, tuple[object, int | None]]]] = {}

    with xlsx.open_workbook(path, inner_suffix) as workbook:
        worksheet = xlsx.sheet(workbook, sheet_name)
        for row_number, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if not months:
                if months := _month_columns(row):
                    header_row = row_number
                continue
            label = row[label_index] if label_index < len(row) else None
            match = _CODE_AND_NAME.match(label) if isinstance(label, str) else None
            if not match:
                continue
            code, name = match.groups()
            if code in parsed:
                raise xlsx.WorkbookError(f"district {code} appears twice (row {row_number})")
            values: dict[date, tuple[object, int | None]] = {}
            for index, month in months.items():
                raw = row[index] if index < len(row) else None
                try:
                    values[month] = (raw, parse_count(raw))
                except ValueError as exc:
                    raise xlsx.WorkbookError(
                        f"row {row_number} ({code} {name}), {month:%Y-%m}: {exc}"
                    ) from exc
            parsed[code] = (name, values)

    if not months:
        raise xlsx.WorkbookError(
            f"sheet {sheet_name!r} has no header row with {MIN_MONTH_COLUMNS}+ month cells"
        )
    if len(set(months.values())) != len(months):
        raise xlsx.WorkbookError(f"header row {header_row} repeats a month")
    if not parsed:
        raise xlsx.WorkbookError(f"no district rows in sheet {sheet_name!r}: check label_column")

    reported = [m for m in months.values() if any((v[m][1] or 0) > 0 for _, v in parsed.values())]
    if not reported:
        raise xlsx.WorkbookError(f"sheet {sheet_name!r} has no non-zero values")
    vintage = max(reported)
    kept = tuple(sorted(m for m in months.values() if m <= vintage))
    _check_nothing_after_vintage(parsed, vintage)

    rows: list[MonthlyUnemployment] = []
    for code, (name, values) in parsed.items():
        for month in kept:
            raw, count = values[month]
            rows.append(
                MonthlyUnemployment(
                    period=month,
                    district_code=code,
                    district_label=name,
                    unemployed=count or None,
                    value_status=_status(raw, count),
                )
            )
    return ParseResult(vintage, kept, tuple(rows))


def _check_nothing_after_vintage(
    parsed: Mapping[str, tuple[str, Mapping[date, tuple[object, int | None]]]], vintage: date
) -> None:
    # By construction no month after the vintage has a non-zero count. A suppressed
    # symbol there would mean the zeros aren't simply "not yet reported".
    for code, (_, values) in parsed.items():
        for month, (raw, count) in values.items():
            if month > vintage and count is None and raw not in (None, ""):
                raise xlsx.WorkbookError(
                    f"{code} has {raw!r} in {month:%Y-%m}, after the reporting month "
                    f"{vintage:%Y-%m}"
                )


def check_controls(
    rows: tuple[MonthlyUnemployment, ...], controls: Mapping[tuple[date, str], int]
) -> int:
    """Compare against published control figures for the months the workbook covers.

    Return how many controls were checked.
    """
    by_key = {(r.period, r.district_code): r.unemployed for r in rows}
    periods = {r.period for r in rows}
    problems: list[str] = []
    checked = 0
    for (period, code), expected in sorted(controls.items()):
        if period not in periods:
            continue
        checked += 1
        actual = by_key.get((period, code))
        if actual != expected:
            found = "missing" if actual is None else f"{actual:,}"
            problems.append(f"{period:%Y-%m} {code}: expected {expected:,}, workbook has {found}")
    if problems:
        raise ControlMismatchError(
            "workbook does not match BA control figures (wrong sheet or month columns?): "
            + "; ".join(problems)
        )
    return checked
