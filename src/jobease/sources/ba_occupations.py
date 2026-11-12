"""BA "Arbeitsmarkt nach Berufen (KldB 2010)": unemployed people, job seekers and registered
vacancies by occupation and skill level, for Germany, West, East and each Land.

One workbook per reporting month. Only the overview sheets ``1.1`` to ``1.19`` are read:
each holds one region and every occupation down to the 3-digit Berufsgruppe, with one row
per skill level (Anforderungsniveau). The occupation code is printed once, on its
``Gesamt`` row, and applies to the level rows below it.

Every measure has the reporting month and the same month a year earlier side by side.
In the BA's tables ``*`` is a suppressed small value and ``-`` means there are no cases;
the first is kept as unknown, the second as zero. The BA publishes no free split by
occupation or skill level below Land level.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from jobease.sources import xlsx
from jobease.sources.numbers import parse_count

Measure = Literal["unemployed", "jobseekers", "vacancies", "vacancy_inflow_12m"]
SkillLevel = Literal["total", "helfer", "fachkraft", "spezialist", "experte", "unknown"]
ValueStatus = Literal["value", "zero", "suppressed", "empty"]

# 0-based column of each measure's reporting-month value. The same month a year earlier is
# in the next column; the two after that are the change, which isn't read.
MEASURE_COLUMNS: dict[Measure, int] = {
    "unemployed": 3,
    "jobseekers": 7,
    "vacancies": 11,
    "vacancy_inflow_12m": 15,
}
# The header text expected above each of those columns.
MEASURE_HEADERS: dict[Measure, str] = {
    "unemployed": "Arbeitslose",
    "jobseekers": "Arbeitsuchende",
    "vacancies": "Gemeldete Arbeitsstellen",
    "vacancy_inflow_12m": "Zugang",
}
CODE, LABEL, LEVEL = 0, 1, 2
# The row under the header numbers the 16 data columns 1..16, from column D.
NUMBERED_COLUMNS = range(3, 19)

SKILL_LEVELS: dict[str, SkillLevel] = {
    "gesamt": "total",
    "helfer": "helfer",
    "fachkraft": "fachkraft",
    "spezialist": "spezialist",
    "experte": "experte",
    "keine angabe": "unknown",
}
OVERVIEW_SHEET = re.compile(r"1\.\d{1,2}")
_LAND = re.compile(r"^\s*(\d{2})\s+(\S.*?)\s*$")
_WIDE_REGIONS = {"deutschland": "DE", "westdeutschland": "W", "ostdeutschland": "O"}
EXPECTED_REGIONS = frozenset({"DE", "W", "O", *(f"{n:02d}" for n in range(1, 17))})
TOTAL = "total"


@dataclass(frozen=True)
class OccupationValue:
    period: date
    region_code: str  # DE, W (West), O (East) or the 2-digit Land code
    region_name: str
    occupation_code: str  # "total" or the KldB 2010 code
    occupation_digits: int  # 0 for the total
    occupation_label: str
    skill_level: SkillLevel
    measure: Measure
    value: int | None  # None unless value_status is "value" or "zero"
    value_status: ValueStatus
    sheet: str
    row_number: int


@dataclass(frozen=True)
class ParseResult:
    vintage: date  # the reporting month
    regions: tuple[str, ...]
    rows: tuple[OccupationValue, ...]

    def count(self, status: ValueStatus) -> int:
        return sum(1 for r in self.rows if r.value_status == status)


def _month(value: object) -> date | None:
    return date(value.year, value.month, 1) if isinstance(value, datetime | date) else None


def _year_before(month: date) -> date:
    return date(month.year - 1, month.month, 1)


def _region(label: object) -> tuple[str, str] | None:
    if not isinstance(label, str):
        return None
    if code := _WIDE_REGIONS.get(label.strip().lower()):
        return code, label.strip()
    if match := _LAND.match(label):
        return match.group(1), match.group(2)
    return None


def _value(raw: object, where: str) -> tuple[int | None, ValueStatus]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, "empty"
    if isinstance(raw, str):
        text = raw.strip()
        if text in {"-", "\u2013"}:
            return 0, "zero"
        if text == "*":
            return None, "suppressed"
    try:
        count = parse_count(raw)
    except ValueError as exc:
        raise xlsx.WorkbookError(f"{where}: {exc}") from exc
    if count is None:  # another symbol parse_count treats as unavailable
        return None, "suppressed"
    if count == 0:
        return 0, "zero"
    return count, "value"


def _is_numbering(row: Sequence[object]) -> bool:
    cells = [row[i] if i < len(row) else None for i in NUMBERED_COLUMNS]
    return all(
        isinstance(c, int | float) and not isinstance(c, bool) and c == n
        for n, c in enumerate(cells, start=1)
    )


def _check_header(
    sheet_name: str, header: Sequence[Sequence[object]], vintage: date, dates_row: Sequence[object]
) -> None:
    """The measure labels and the two month columns must sit where they're read from."""
    for measure, column in MEASURE_COLUMNS.items():
        label = MEASURE_HEADERS[measure]
        texts = [str(r[column]).strip() for r in header if column < len(r) and r[column]]
        if not any(t.startswith(label) for t in texts):
            raise xlsx.WorkbookError(
                f"sheet {sheet_name}: no {label!r} header above column {column + 1}"
            )
        current = _month(dates_row[column] if column < len(dates_row) else None)
        before = _month(dates_row[column + 1] if column + 1 < len(dates_row) else None)
        if current != vintage or before != _year_before(vintage):
            raise xlsx.WorkbookError(
                f"sheet {sheet_name}: {measure} columns show {current} and {before}, "
                f"expected {vintage} and {_year_before(vintage)}"
            )


def parse_sheet(
    sheet_name: str, rows: Iterable[Sequence[object]]
) -> tuple[date, tuple[str, str], list[OccupationValue]]:
    """Read one overview sheet: its reporting month, its region and every value."""
    header: list[Sequence[object]] = []
    region: tuple[str, str] | None = None
    vintage: date | None = None
    values: list[OccupationValue] = []
    occupation: tuple[str, int, str] | None = None
    seen: set[tuple[str, SkillLevel]] = set()
    in_table = False

    for row_number, row in enumerate(rows, start=1):
        first = row[CODE] if row else None
        if not in_table:
            if _is_numbering(row):
                if region is None or vintage is None:
                    raise xlsx.WorkbookError(
                        f"sheet {sheet_name}: no region or reporting date above the table"
                    )
                if len(header) < 2:
                    raise xlsx.WorkbookError(f"sheet {sheet_name}: no header rows")
                _check_header(sheet_name, header[:-1], vintage, header[-1])
                in_table = True
                continue
            region = region or _region(first)
            vintage = vintage or _month(first)
            header.append(row)
            continue

        level_text = row[LEVEL] if len(row) > LEVEL else None
        if isinstance(first, str) and first.strip().lower() == "insgesamt":
            occupation = (TOTAL, 0, "Insgesamt")
        elif first is not None:
            code = str(first).strip()
            if not code.isdigit():
                if level_text is None:
                    break  # a footnote: the table has ended
                raise xlsx.WorkbookError(f"sheet {sheet_name} row {row_number}: code {first!r}")
            label = row[LABEL] if len(row) > LABEL else None
            occupation = (code, len(code), str(label).strip() if label else code)
        if level_text is None:
            continue
        level = SKILL_LEVELS.get(str(level_text).strip().lower())
        if level is None:
            raise xlsx.WorkbookError(
                f"sheet {sheet_name} row {row_number}: unknown skill level {level_text!r}"
            )
        if occupation is None:
            raise xlsx.WorkbookError(f"sheet {sheet_name} row {row_number}: no occupation code")
        code, digits, label = occupation
        if (code, level) in seen:
            raise xlsx.WorkbookError(
                f"sheet {sheet_name} row {row_number}: {code} {level} appears twice"
            )
        seen.add((code, level))
        assert region is not None and vintage is not None  # set before in_table
        for measure, column in MEASURE_COLUMNS.items():
            for period, index in ((vintage, column), (_year_before(vintage), column + 1)):
                where = f"sheet {sheet_name} row {row_number} ({code} {level}, {measure})"
                value, status = _value(row[index] if index < len(row) else None, where)
                values.append(
                    OccupationValue(
                        period=period,
                        region_code=region[0],
                        region_name=region[1],
                        occupation_code=code,
                        occupation_digits=digits,
                        occupation_label=label,
                        skill_level=level,
                        measure=measure,
                        value=value,
                        value_status=status,
                        sheet=sheet_name,
                        row_number=row_number,
                    )
                )

    if not in_table:
        raise xlsx.WorkbookError(f"sheet {sheet_name}: no numbered header row (columns 1-16)")
    if (TOTAL, "total") not in seen:
        raise xlsx.WorkbookError(f"sheet {sheet_name}: no 'Insgesamt' row")
    assert region is not None and vintage is not None
    return vintage, region, values


def parse_workbook(path: Path) -> ParseResult:
    """Read every overview sheet. All must share one reporting month and together cover
    Germany, West, East and the 16 Länder exactly once."""
    vintages: set[date] = set()
    regions: dict[str, str] = {}
    rows: list[OccupationValue] = []
    with xlsx.open_workbook(path) as workbook:
        names = [n for n in workbook.sheetnames if OVERVIEW_SHEET.fullmatch(n)]
        if not names:
            raise xlsx.WorkbookError(f"{path.name}: no overview sheets 1.1 to 1.19")
        for name in names:
            worksheet = xlsx.sheet(workbook, name)
            vintage, (code, _), values = parse_sheet(name, worksheet.iter_rows(values_only=True))
            if code in regions:
                raise xlsx.WorkbookError(
                    f"{path.name}: region {code} is in both {regions[code]} and {name}"
                )
            regions[code] = name
            vintages.add(vintage)
            rows.extend(values)
    if len(vintages) != 1:
        raise xlsx.WorkbookError(f"{path.name}: sheets disagree on the month: {sorted(vintages)}")
    if set(regions) != EXPECTED_REGIONS:
        missing = sorted(EXPECTED_REGIONS - set(regions))
        extra = sorted(set(regions) - EXPECTED_REGIONS)
        raise xlsx.WorkbookError(f"{path.name}: regions missing {missing}, unexpected {extra}")
    return ParseResult(vintages.pop(), tuple(sorted(regions)), tuple(rows))
