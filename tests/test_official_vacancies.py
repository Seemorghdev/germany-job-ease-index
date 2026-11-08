from datetime import date

from jobease.official_vacancies import VacancyCsv, compose_index, parse_vacancy_csv


def test_ba_csv_values_are_parsed_without_changing_published_count() -> None:
    payload = (
        "Gemeldete Arbeitsstellen\n"
        "Kreis:; Köln, Stadt\n"
        "Gebietsstand:; Oktober 2026\n"
        "Berichtsmonat:; Oktober 2025 bis Oktober 2026\n"
        "Datenstand:;Oktober 2026\n\n"
        "Ausgewählte Merkmale;Oktober 2026;September 2026\n"
        "Bestand Arbeitsstellen;44.350;44.340\n"
        "Zugang Arbeitsstellen;1.400;1.780\n"
    ).encode()
    parsed = parse_vacancy_csv(payload)

    assert parsed.stock == 44_350
    assert parsed.area_label == "Köln, Stadt"
    assert parsed.period == date(2026, 10, 1)


def test_index_includes_only_matching_district_code_label_and_month() -> None:
    cities = [
        {
            "city": "Köln",
            "municipality_ags": "05315000",
            "district_code": "05315",
            "area_type": "Kreisfreie Stadt",
            "population": 1_025_523,
        },
        {
            "city": "Fake Köln",
            "municipality_ags": "99999000",
            "district_code": "99999",
            "area_type": "Kreisfreie Stadt",
            "population": 100_000,
        },
    ]
    unemployment = {"05315": ("Köln, Stadt", 55_984), "99999": ("Wrong district", 10)}
    vacancies = {
        "05315": (VacancyCsv("Köln, Stadt", date(2026, 10, 1), 44_350), "hash", "url"),
        "99999": (VacancyCsv("Different area", date(2026, 10, 1), 1_000), "hash2", "url2"),
    }

    indexed = compose_index(cities, unemployment, vacancies, period=date(2026, 10, 1))

    assert len(indexed) == 1
    assert indexed[0].district_code == "05315"
    assert indexed[0].city == "Köln"


def test_rate_is_project_calculation_of_unchanged_ba_counts() -> None:
    cities = [
        {
            "city": "Köln",
            "municipality_ags": "05315000",
            "district_code": "05315",
            "area_type": "Kreisfreie Stadt",
            "population": 1_025_523,
        }
    ]
    indexed = compose_index(
        cities,
        {"05315": ("Köln, Stadt", 55_984)},
        {"05315": (VacancyCsv("Köln, Stadt", date(2026, 10, 1), 44_350), "hash", "url")},
        period=date(2026, 10, 1),
    )

    assert indexed[0].vacancy_stock == 44_350
    assert indexed[0].unemployed == 55_984
    assert indexed[0].project_vacancies_per_1000_registered_unemployed == 44_350 / 55_984 * 1_000
