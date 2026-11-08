"""Local-only city index from BA Kreis vacancies and registered unemployment.

This path is deliberately independent of the listing warehouse and the Jobbörse client.
BA source values are retained verbatim as integers after parsing the BA's published
German thousands separators; all ratios and ranks are project calculations.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import quote

from jobease.config import GVISYS_DEFAULT_COLUMNS, REPO_ROOT, Settings
from jobease.http import PoliteClient
from jobease.raw_store import RawStore
from jobease.sources import destatis_gvisys
from jobease.sources.ba_unemployment import parse_workbook as parse_unemployment
from jobease.sources.numbers import parse_count

VACANCY_CSV_URL = (
    "https://statistik-dr.arbeitsagentur.de/bifrontend/bids-api/ct/v1/tableFetch/csv/"
    "EckwerteTabelleSTEA?Kreis={label}"
)
_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


class VacancySourceError(ValueError):
    """The BA CSV is missing an expected area, period, or published value."""


@dataclass(frozen=True)
class VacancyCsv:
    area_label: str
    period: date
    stock: int


@dataclass(frozen=True)
class CityIndexRow:
    city: str
    municipality_ags: str
    district_code: str
    district_label: str
    area_type: str
    population: int
    unemployed: int
    vacancy_stock: int
    project_vacancies_per_1000_registered_unemployed: float
    project_vacancy_population_share: float
    project_combined_rank: int
    raw_sha256: str
    vacancy_url: str


@dataclass(frozen=True)
class IndexSummary:
    period: date
    unemployment_source: Path
    geographies: int
    vacancy_csvs: int
    included: int
    excluded: int
    index: Path


def parse_vacancy_csv(data: bytes) -> VacancyCsv:
    """Read BA's current Eckwerte CSV while retaining its published integer count."""
    text = data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    metadata: dict[str, str] = {}
    for row in rows:
        if len(row) >= 2 and row[0].strip().rstrip(":") in {"Kreis", "Gebietsstand"}:
            metadata[row[0].strip().rstrip(":")] = row[1].strip()
    label = metadata.get("Kreis")
    if not label:
        raise VacancySourceError("BA CSV has no Kreis label")

    header_index = next(
        (i for i, row in enumerate(rows) if row and row[0].strip() == "Ausgewählte Merkmale"),
        None,
    )
    if header_index is None:
        raise VacancySourceError("BA CSV has no 'Ausgewählte Merkmale' header")
    header = rows[header_index]
    if len(header) < 2:
        raise VacancySourceError("BA CSV has no current period column")
    match = re.fullmatch(r"\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})\s*", header[1])
    if not match or match.group(1).lower() not in _MONTHS:
        raise VacancySourceError(f"unrecognized BA reporting month {header[1]!r}")
    period = date(int(match.group(2)), _MONTHS[match.group(1).lower()], 1)
    if (
        metadata.get("Gebietsstand")
        and metadata["Gebietsstand"].casefold() != header[1].strip().casefold()
    ):
        raise VacancySourceError("BA Gebietsstand and current table column disagree")
    for row in rows[header_index + 1 :]:
        if row and row[0].strip() == "Bestand Arbeitsstellen":
            if len(row) < 2:
                break
            count = parse_count(row[1])
            if count is None:
                raise VacancySourceError("BA vacancy stock is suppressed or empty")
            return VacancyCsv(label, period, count)
    raise VacancySourceError("BA CSV has no Bestand Arbeitsstellen row")


def build_city_geography(
    gvisys_file: Path,
    *,
    changes_file: Path,
    minimum_population: int = 100_000,
    minimum_district_coverage: float = 0.5,
) -> list[dict[str, object]]:
    """Reproduce the original 69-city cut from official AGS/population inputs."""
    parsed = destatis_gvisys.parse_workbook(
        gvisys_file, sheet_name=None, columns=GVISYS_DEFAULT_COLUMNS
    )
    remaps: dict[str, str] = {}
    with changes_file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("municipality_ags") and row.get("district_code"):
                remaps[row["municipality_ags"]] = row["district_code"]
    district_populations: dict[str, int] = defaultdict(int)
    for municipality in parsed.municipalities:
        if municipality.population is not None:
            district_populations[remaps.get(municipality.ags, municipality.ags[:5])] += (
                municipality.population
            )
    districts = {district.district_code: district for district in parsed.districts}
    output: list[dict[str, object]] = []
    for municipality in parsed.municipalities:
        population = municipality.population
        if population is None or population < minimum_population:
            continue
        code = remaps.get(municipality.ags, municipality.ags[:5])
        district_population = district_populations.get(code, 0)
        if not district_population:
            raise VacancySourceError(f"no population for district {code} ({municipality.name})")
        coverage = population / district_population
        if coverage < minimum_district_coverage:
            continue
        district = districts.get(code)
        output.append(
            {
                "city": destatis_gvisys.search_name(municipality.name),
                "municipality_ags": municipality.ags,
                "district_code": code,
                "district_label_destatis": district.name if district else "",
                "area_type": _district_type(district.type_code if district else None),
                "population": population,
                "district_coverage": coverage,
            }
        )
    return sorted(output, key=lambda row: str(row["city"]).casefold())


def _district_type(type_code: str | None) -> str:
    return {
        "41": "Kreisfreie Stadt",
        "42": "Stadtkreis",
        "43": "Kreis",
        "44": "Landkreis",
        "45": "Regionalverband",
    }.get(type_code or "", "Unbekannt")


def compose_index(
    cities: list[dict[str, object]],
    unemployment_rows: dict[str, tuple[str, int]],
    vacancy_rows: dict[str, tuple[VacancyCsv, str, str]],
    *,
    period: date,
) -> list[CityIndexRow]:
    """Join by district AGS, requiring exact same-month data on both source sides."""
    joined: list[CityIndexRow] = []
    for city in cities:
        code = str(city["district_code"])
        if code not in unemployment_rows or code not in vacancy_rows:
            continue
        unemployed_label, unemployed = unemployment_rows[code]
        vacancy, digest, url = vacancy_rows[code]
        if vacancy.area_label != unemployed_label:
            continue
        if vacancy.period != period or unemployed <= 0:
            continue
        stock = vacancy.stock
        population = cast(int, city["population"])
        joined.append(
            CityIndexRow(
                city=str(city["city"]),
                municipality_ags=str(city["municipality_ags"]),
                district_code=code,
                district_label=unemployed_label,
                area_type=str(city["area_type"]),
                population=population,
                unemployed=unemployed,
                vacancy_stock=stock,
                project_vacancies_per_1000_registered_unemployed=stock / unemployed * 1000,
                project_vacancy_population_share=stock / population,
                project_combined_rank=0,
                raw_sha256=digest,
                vacancy_url=url,
            )
        )
    ordered = sorted(
        joined,
        key=lambda row: (
            -row.project_vacancies_per_1000_registered_unemployed,
            row.city.casefold(),
        ),
    )
    return [
        CityIndexRow(**{**row.__dict__, "project_combined_rank": index})
        for index, row in enumerate(ordered, 1)
    ]


def latest_unemployment(
    path: Path, *, sheet_name: str, label_column: str, inner_suffix: str | None
) -> tuple[date, dict[str, tuple[str, int]]]:
    parsed = parse_unemployment(
        path, sheet_name=sheet_name, label_column=label_column, inner_suffix=inner_suffix
    )
    period = parsed.vintage
    rows = {
        row.district_code: (row.district_label, row.unemployed)
        for row in parsed.rows
        if row.period == period and row.unemployed is not None
    }
    return period, rows


def write_index(rows: list[CityIndexRow], path: Path) -> None:
    """Write a local derived CSV; all calculated fields say 'project' in their names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CityIndexRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(row.__dict__ for row in rows)


def refresh_index(settings: Settings) -> IndexSummary:
    """Fetch official BA Kreis CSVs, then write a local, standalone monthly index.

    ``settings`` is the regular ``jobease.config.Settings`` object. This function reads
    source input files and writes only under ``data/raw`` and ``data/official-vacancies``;
    it never opens the listing warehouse or calls the Jobbörse client.
    """
    geographies = build_city_geography(
        settings.gvisys.file,
        changes_file=REPO_ROOT / "dbt" / "seeds" / "district_changes.csv",
        minimum_population=settings.min_population,
    )
    source_versions = []
    for path in settings.ba.files():
        parsed = parse_unemployment(
            path,
            sheet_name=settings.ba.sheet,
            label_column=settings.ba.label_column,
            inner_suffix=settings.ba.inner_suffix,
        )
        source_versions.append((parsed.vintage, path, parsed))
    if not source_versions:
        raise VacancySourceError(f"no BA unemployment source files found in {settings.ba.dir}")
    period, source_file, unemp_parsed = max(source_versions, key=lambda row: row[0])
    unemployment_artifact = RawStore(settings.raw_dir).put_file(
        "ba_unemployment", source_file, origin=f"local BA issue {source_file.name}"
    )
    unemp = {
        row.district_code: (row.district_label, row.unemployed)
        for row in unemp_parsed.rows
        if row.period == period and row.unemployed is not None
    }
    store = RawStore(settings.raw_dir)
    vacancy_by_code: dict[str, tuple[VacancyCsv, str, str]] = {}
    audit_rows: list[dict[str, object]] = []
    with PoliteClient(
        min_interval_s=1.0,
        max_retries=4,
        max_backoff_s=120.0,
        timeout_s=60.0,
    ) as client:
        for city in geographies:
            code = str(city["district_code"])
            if code not in unemp:
                audit_rows.append(
                    _audit_row(
                        city,
                        "",
                        "",
                        "",
                        "not comparable: no BA unemployment area",
                        unemployment_type=str(city["area_type"]),
                    )
                )
                continue
            unemp_label, _ = unemp[code]
            url = vacancy_url(unemp_label)
            response = client.get(url)
            vacancy = parse_vacancy_csv(response.content)
            artifact = store.put_bytes("ba_vacancies", response.content, suffix=".csv", origin=url)
            vacancy_by_code[code] = (vacancy, artifact.sha256, url)
            same_code = (
                True  # URL uses the BA unemployment label; both source files are Kreis tables.
            )
            same_label = vacancy.area_label == unemp_label
            same_month = vacancy.period == period
            status = (
                "matched"
                if same_code and same_label and same_month
                else (
                    "not comparable: "
                    + ", ".join(
                        reason
                        for reason, ok in (
                            ("area label mismatch", same_label),
                            ("reporting month mismatch", same_month),
                        )
                        if not ok
                    )
                )
            )
            audit_rows.append(
                _audit_row(
                    city,
                    vacancy.area_label,
                    vacancy.period.strftime("%Y-%m"),
                    artifact.sha256,
                    status,
                    vacancy_type=str(city["area_type"]),
                    unemployment_type=str(city["area_type"]),
                    unemployment_label=unemp_label,
                    vacancy_url=url,
                )
            )

    rows = compose_index(geographies, unemp, vacancy_by_code, period=period)
    output = REPO_ROOT / "data" / "official-vacancies"
    output.mkdir(parents=True, exist_ok=True)
    suffix = period.strftime("%Y-%m")
    write_index(rows, output / f"city_vacancy_ease-{suffix}.csv")
    with (output / f"geography_audit-{suffix}.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = list(audit_rows[0]) if audit_rows else []
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audit_rows)
    with (output / f"ba_vacancy_manifest-{suffix}.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        manifest = csv.writer(handle)
        manifest.writerow(
            [
                "district_code",
                "district_label",
                "reporting_period",
                "raw_sha256",
                "raw_path",
                "source_url",
                "unemployment_source_sha256",
                "unemployment_source_path",
            ]
        )
        for code, (value, digest, url) in sorted(vacancy_by_code.items()):
            manifest.writerow(
                [
                    code,
                    value.area_label,
                    value.period.isoformat(),
                    digest,
                    f"data/raw/ba_vacancies/{digest[:2]}/{digest}.csv",
                    url,
                    unemployment_artifact.sha256,
                    str(unemployment_artifact.path.relative_to(REPO_ROOT)),
                ]
            )
    return IndexSummary(
        period=period,
        unemployment_source=source_file,
        geographies=len(geographies),
        vacancy_csvs=len(vacancy_by_code),
        included=len(rows),
        excluded=len(geographies) - len(rows),
        index=output / f"city_vacancy_ease-{suffix}.csv",
    )


def _audit_row(
    city: dict[str, object],
    vacancy_label: str,
    vacancy_period: str,
    digest: str,
    status: str,
    *,
    vacancy_type: str = "",
    unemployment_type: str = "",
    unemployment_label: str = "",
    vacancy_url: str = "",
) -> dict[str, object]:
    code = str(city["district_code"])
    return {
        "city": city["city"],
        "municipality_ags": city["municipality_ags"],
        "city_area_type_from_AGS": city["area_type"],
        "vacancy_area_label_from_BA_CSV": vacancy_label,
        "vacancy_area_type_from_AGS_crosswalk": vacancy_type,
        "vacancy_numeric_code_in_csv": "not provided by CSV",
        "vacancy_district_code_crosswalk": code,
        "unemployment_area_label_from_BA_workbook": unemployment_label,
        "unemployment_area_type_from_AGS_crosswalk": unemployment_type,
        "unemployment_district_code_from_BA_workbook": code,
        "vacancy_period": vacancy_period,
        "district_code_match_by_crosswalk": bool(vacancy_label)
        and vacancy_label == unemployment_label,
        "area_label_match": bool(vacancy_label) and vacancy_label == unemployment_label,
        "comparison_status": status,
        "vacancy_raw_sha256": digest,
        "vacancy_api_url": vacancy_url,
    }


def raw_store(root: Path | None = None) -> RawStore:
    return RawStore(root or REPO_ROOT / "data" / "raw")


def vacancy_url(label: str) -> str:
    return VACANCY_CSV_URL.format(label=quote(label, safe=""))
