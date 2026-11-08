from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from jobease import vacancy_export
from jobease.vacancy_export import VacancyIndexError, export_vacancies, latest_index, read_index

FIELDS = [
    "city",
    "municipality_ags",
    "district_code",
    "district_label",
    "area_type",
    "population",
    "unemployed",
    "vacancy_stock",
    "vacancy_stock_year_before",
    "project_vacancies_per_1000_registered_unemployed",
    "project_vacancy_population_share",
    "project_year_on_year",
    "project_is_ranked",
    "project_not_ranked_reason",
    "project_check",
    "project_combined_rank",
    "raw_sha256",
    "vacancy_url",
]


def _row(city: str, ags: str, rank: str, rate: float, **extra: str) -> dict[str, str]:
    row = {
        "city": city,
        "municipality_ags": ags,
        "district_code": ags[:5],
        "district_label": f"{city}, Stadt",
        "area_type": "Kreisfreie Stadt",
        "population": "100000",
        "unemployed": "4000",
        "vacancy_stock": "1000",
        "vacancy_stock_year_before": "900",
        "project_vacancies_per_1000_registered_unemployed": str(rate),
        "project_vacancy_population_share": "0.01",
        "project_year_on_year": "1.1",
        "project_is_ranked": "True" if rank else "False",
        "project_not_ranked_reason": "",
        "project_check": "",
        "project_combined_rank": rank,
        "raw_sha256": "ab" * 32,
        "vacancy_url": f"https://statistik-dr.arbeitsagentur.de/{ags}",
    }
    return {**row, **extra}


def _write(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


ROWS = [
    _row("Ulm", "08421000", "1", 504.35865),
    _row("Berlin", "11000000", "2", 95.1),
    _row("Remscheid", "05120000", "3", 196.1, project_check="stock ×2.3 in a year: review before publishing"),
    _row("Köln", "05315000", "", 900.0, project_not_ranked_reason="Bundeswehr posts"),
]


def test_latest_index_picks_the_newest_month(tmp_path: Path) -> None:
    _write(tmp_path / "city_vacancy_ease-2026-09.csv", ROWS)
    _write(tmp_path / "city_vacancy_ease-2026-10.csv", ROWS)
    _write(tmp_path / "city_vacancy_ease.csv", ROWS)  # an undated leftover is ignored
    period, path = latest_index(tmp_path)
    assert (period, path.name) == ("2026-10", "city_vacancy_ease-2026-10.csv")


def test_latest_index_needs_a_file(tmp_path: Path) -> None:
    with pytest.raises(VacancyIndexError, match="vacancy-index"):
        latest_index(tmp_path)


def test_read_index_orders_ranked_first_and_rounds(tmp_path: Path) -> None:
    cities = read_index(_write(tmp_path / "city_vacancy_ease-2026-10.csv", ROWS))
    assert [c.city for c in cities] == ["Ulm", "Berlin", "Remscheid", "Köln"]
    assert cities[0].vacancies_per_1000_unemployed == 504.4
    assert cities[2].note == "stock ×2.3 in a year; no explanation found yet"
    assert not cities[3].is_ranked and cities[3].rank is None


def test_read_index_rejects_gaps_in_the_ranking(tmp_path: Path) -> None:
    gappy = [ROWS[0], _row("Berlin", "11000000", "3", 95.1)]
    with pytest.raises(VacancyIndexError, match="ranks"):
        read_index(_write(tmp_path / "city_vacancy_ease-2026-10.csv", gappy))


def test_export_writes_marked_own_calculations(tmp_path: Path) -> None:
    index_dir, out = tmp_path / "index", tmp_path / "exports"
    _write(index_dir / "city_vacancy_ease-2026-10.csv", ROWS)

    table, meta = export_vacancies(out, index_dir)

    with table.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == list(vacancy_export.COLUMNS)
    assert (rows[0]["rank"], rows[0]["city"]) == ("1", "Ulm")
    summary = json.loads(meta.read_text(encoding="utf-8"))
    assert summary["period"] == "2026-10"
    assert summary["ranked_cities"] == 3
    assert summary["berlin"] == {"rank": 2, "rate": 95.1}
    assert summary["not_ranked"] == [{"city": "Köln", "reason": "Bundeswehr posts"}]
    assert "eigene Berechnungen" in summary["source"]
    assert "own calculations" in summary["notice"]
    text = table.read_text(encoding="utf-8") + meta.read_text(encoding="utf-8")
    for private in ("referenznummer", "Jobbörse", "jobsuche"):
        assert private not in text
