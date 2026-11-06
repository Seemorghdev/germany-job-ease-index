"""Destatis Gemeindeverzeichnis (GV-ISys): municipalities and districts with official codes.

Record types (column "Satzart"): ``40`` is a district (Kreis), ``60`` is a municipality.
The 8-digit AGS of a municipality is Land(2) + RB(1) + Kreis(2) + Gemeinde(3); its first
five digits are its district code. Joining on these codes, never on names, is what keeps
"München" (city, 09162) apart from "München" (Landkreis, 09184).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jobease.sources import xlsx
from jobease.sources.numbers import parse_code, parse_count, parse_decimal

DISTRICT_RECORD = "40"
MUNICIPALITY_RECORD = "60"


@dataclass(frozen=True)
class Municipality:
    ags: str
    name: str
    population: int | None
    area_km2: float | None


@dataclass(frozen=True)
class District:
    district_code: str
    name: str
    type_code: str | None


@dataclass(frozen=True)
class ParseResult:
    municipalities: tuple[Municipality, ...]
    districts: tuple[District, ...]
    # Unpopulated entries outside any district (e.g. coastal waters). Kept out of the load.
    excluded: tuple[Municipality, ...]


def _pick_sheet(sheetnames: list[str], requested: str | None) -> str:
    if requested:
        return requested
    matches = [n for n in sheetnames if "gemeinde" in n.casefold()]
    if not matches:
        raise xlsx.WorkbookError(f"no sheet name contains 'Gemeinde'; available: {sheetnames}")
    return matches[0]


def parse_workbook(
    path: Path, *, sheet_name: str | None, columns: Mapping[str, str]
) -> ParseResult:
    municipalities: dict[str, Municipality] = {}
    districts: dict[str, District] = {}
    with xlsx.open_workbook(path) as workbook:
        worksheet = xlsx.sheet(workbook, _pick_sheet(workbook.sheetnames, sheet_name))
        for row_number, cell in xlsx.iter_columns(worksheet, columns):
            try:
                _read_row(cell, municipalities, districts)
            except ValueError as exc:
                raise xlsx.WorkbookError(f"row {row_number}: {exc}") from exc

    if not municipalities or not districts:
        raise xlsx.WorkbookError(
            f"found {len(municipalities)} municipalities and {len(districts)} districts; "
            "check the sheet and column mapping"
        )
    orphans = [m for m in municipalities.values() if m.ags[:5] not in districts]
    populated = [m for m in orphans if m.population]
    if populated:
        sample = ", ".join(f"{m.ags} {m.name} ({m.population:,})" for m in populated[:10])
        raise xlsx.WorkbookError(f"populated municipalities outside any district: {sample}")
    kept = tuple(m for m in municipalities.values() if m.ags[:5] in districts)
    return ParseResult(kept, tuple(districts.values()), tuple(orphans))


def _read_row(
    cell: Mapping[str, object],
    municipalities: dict[str, Municipality],
    districts: dict[str, District],
) -> None:
    record = parse_code(cell["record_type"], 2)
    if record not in (DISTRICT_RECORD, MUNICIPALITY_RECORD):
        return
    land = parse_code(cell["land"], 2)
    rb = parse_code(cell["rb"], 1)
    kreis = parse_code(cell["kreis"], 2)
    name = str(cell["name"] or "").strip()
    if land is None or rb is None or kreis is None or not name:
        raise ValueError(f"incomplete code or name: {dict(cell)}")
    district_code = land + rb + kreis

    if record == DISTRICT_RECORD:
        if district_code in districts:
            raise ValueError(f"duplicate district {district_code}")
        districts[district_code] = District(district_code, name, parse_code(cell["text_code"], 2))
        return

    gem = parse_code(cell["gem"], 3)
    if gem is None:
        raise ValueError(f"municipality {name!r} has no Gemeinde code")
    ags = district_code + gem
    if ags in municipalities:
        raise ValueError(f"duplicate AGS {ags}")
    municipalities[ags] = Municipality(
        ags, name, parse_count(cell["population"]), parse_decimal(cell["area_km2"])
    )


def search_name(official_name: str) -> str:
    """The plain place name: ``"München, Landeshauptstadt"`` -> ``"München"``."""
    return official_name.split(",", 1)[0].strip()
