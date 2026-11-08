"""Publish the official-vacancy city index: ``data/exports/city_vacancy_ease.csv`` and
``summary.json``.

The source is the local index ``jobease vacancy-index`` writes into
``data/official-vacancies/`` from the BA's statistics interface (Gemeldete Arbeitsstellen
and Arbeitslose per Kreis). Everything here is an aggregate the BA publishes, plus our own
ratio and rank, which the BA's terms ask to be marked as our own calculations.

Job-board data (BA Jobbörse) is never published: its terms forbid automated collection.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobease.config import REPO_ROOT

INDEX_DIR = REPO_ROOT / "data" / "official-vacancies"
EXPORT_DIR = REPO_ROOT / "data" / "exports"

SOURCE = (
    "Statistik der Bundesagentur für Arbeit: Gemeldete Arbeitsstellen und Arbeitslose "
    "nach Kreisen (statistik.arbeitsagentur.de); eigene Berechnungen"
)
NOTICE = (
    "Vacancies per 1,000 unemployed, the ranking and the year-on-year ratio are own "
    "calculations by germany-job-ease-index, not figures published by the BA."
)

COLUMNS = (
    "rank",
    "city",
    "ags",
    "district_code",
    "district_name",
    "population",
    "unemployed",
    "vacancies",
    "vacancies_year_before",
    "vacancies_per_1000_unemployed",
    "is_ranked",
    "not_ranked_reason",
    "note",
    "source_url",
)


class VacancyIndexError(RuntimeError):
    """The local official index is missing or doesn't look right."""


@dataclass(frozen=True)
class PublishedCity:
    rank: int | None
    city: str
    ags: str
    district_code: str
    district_name: str
    population: int
    unemployed: int
    vacancies: int
    vacancies_year_before: int | None
    vacancies_per_1000_unemployed: float
    is_ranked: bool
    not_ranked_reason: str
    note: str  # a reviewed but unexplained jump, shown next to the number
    source_url: str


def latest_index(index_dir: Path = INDEX_DIR) -> tuple[str, Path]:
    """The newest dated index, ``city_vacancy_ease-YYYY-MM.csv``, and its month."""
    dated = sorted(index_dir.glob("city_vacancy_ease-????-??.csv"))
    if not dated:
        raise VacancyIndexError(
            f"no city_vacancy_ease-YYYY-MM.csv in {index_dir}: run `jobease vacancy-index`"
        )
    path = dated[-1]
    return path.stem.removeprefix("city_vacancy_ease-"), path


def _int(value: str) -> int | None:
    return int(value) if value.strip() else None


def read_index(path: Path) -> list[PublishedCity]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise VacancyIndexError(f"{path.name} is empty")
    cities = []
    for row in rows:
        ranked = row["project_is_ranked"] == "True"
        rank = _int(row["project_combined_rank"])
        if ranked != (rank is not None):
            raise VacancyIndexError(f"{path.name}: {row['city']} is_ranked/rank disagree")
        check = row["project_check"].removesuffix(": review before publishing")
        cities.append(
            PublishedCity(
                rank=rank,
                city=row["city"],
                ags=row["municipality_ags"],
                district_code=row["district_code"],
                district_name=row["district_label"],
                population=int(row["population"]),
                unemployed=int(row["unemployed"]),
                vacancies=int(row["vacancy_stock"]),
                vacancies_year_before=_int(row["vacancy_stock_year_before"]),
                vacancies_per_1000_unemployed=round(
                    float(row["project_vacancies_per_1000_registered_unemployed"]), 1
                ),
                is_ranked=ranked,
                not_ranked_reason=row["project_not_ranked_reason"],
                note=f"{check}; no explanation found yet" if check else "",
                source_url=row["vacancy_url"],
            )
        )
    ranks = sorted(c.rank for c in cities if c.rank is not None)
    if ranks != list(range(1, len(ranks) + 1)):
        raise VacancyIndexError(f"{path.name}: ranks aren't 1..{len(ranks)}")
    return sorted(cities, key=lambda c: (c.rank is None, c.rank or 0, c.city))


def summary(period: str, cities: list[PublishedCity]) -> dict[str, Any]:
    ranked = [c for c in cities if c.is_ranked]
    berlin = next((c for c in cities if c.ags == "11000000"), None)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "period": period,
        "measure": "vacancies registered with the BA per 1,000 registered unemployed, per Kreis",
        "source": SOURCE,
        "notice": NOTICE,
        "cities": len(cities),
        "ranked_cities": len(ranked),
        "top": [
            {"rank": c.rank, "city": c.city, "rate": c.vacancies_per_1000_unemployed}
            for c in ranked[:10]
        ],
        "berlin": None
        if berlin is None
        else {"rank": berlin.rank, "rate": berlin.vacancies_per_1000_unemployed},
        "not_ranked": [
            {"city": c.city, "reason": c.not_ranked_reason} for c in cities if not c.is_ranked
        ],
        "notes": [{"city": c.city, "note": c.note} for c in cities if c.note],
    }


def export_vacancies(out_dir: Path = EXPORT_DIR, index_dir: Path = INDEX_DIR) -> list[Path]:
    period, path = latest_index(index_dir)
    cities = read_index(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = out_dir / "city_vacancy_ease.csv"
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({k: getattr(c, k) for k in COLUMNS} for c in cities)
    meta = out_dir / "summary.json"
    meta.write_text(
        json.dumps(summary(period, cities), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return [table, meta]
