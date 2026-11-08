"""Export the district map's data as ``docs/map/data.js``: aggregates only.

A script file rather than JSON, so ``docs/map/index.html`` also works when opened straight
from disk: browsers refuse ``fetch`` on ``file://`` pages, but load a ``<script src>``.

Districts come from the warehouse (BA unemployment, BKG boundaries). City figures come
from the official-vacancy index (``vacancy_export``); the warehouse only adds each city's
position. Job-board figures are never part of the map.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from jobease.config import REPO_ROOT, Settings
from jobease.sources.bkg import rewind_for_d3, round_coordinates
from jobease.vacancy_export import INDEX_DIR, PublishedCity, latest_index, read_index

MAP_DIR = REPO_ROOT / "docs" / "map"
SOURCES = [
    "Statistik der Bundesagentur für Arbeit (registered vacancies and unemployed per district)",
    "own calculations",
    "Destatis Gemeindeverzeichnis (residents)",
    "© GeoBasis-DE / BKG (2026), dl-de/by-2-0 (boundaries)",
]
OUTSIDE_INDEX = (
    "City makes up less than half of its district, so district figures say little about it"
)


def _records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _number(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _feature(geometry_json: str, properties: dict[str, Any]) -> dict[str, Any]:
    geometry = rewind_for_d3(round_coordinates(json.loads(geometry_json)))
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _city(place: dict[str, Any], indexed: PublishedCity | None) -> dict[str, Any]:
    base = {
        "ags": place["ags"],
        "city": place["city"],
        "population": place["population"],
        "lon": _number(place["lon"], 4),
        "lat": _number(place["lat"], 4),
    }
    if indexed is None:
        return {
            **base,
            "is_ranked": False,
            "rank": None,
            "rate": None,
            "vacancies": None,
            "vacancies_year_before": None,
            "unemployed": None,
            "not_ranked_reason": OUTSIDE_INDEX,
            "note": "",
        }
    return {
        **base,
        "is_ranked": indexed.is_ranked,
        "rank": indexed.rank,
        "rate": indexed.vacancies_per_1000_unemployed,
        "vacancies": indexed.vacancies,
        "vacancies_year_before": indexed.vacancies_year_before,
        "unemployed": indexed.unemployed,
        "not_ranked_reason": indexed.not_ranked_reason,
        "note": indexed.note,
    }


def build_map_data(
    con: duckdb.DuckDBPyConnection, cities: list[PublishedCity], vacancy_period: str
) -> dict[str, Any]:
    districts = _records(con, "select * from marts.mart_district_map order by district_code")
    lands = _records(
        con,
        "select code, name, geometry from staging.stg_bkg__areas "
        "where level = 'land' order by code",
    )
    places = _records(
        con, "select ags, city, population, lon, lat from marts.mart_city_map order by ags"
    )
    period = next((d["unemployment_period"] for d in districts if d["unemployment_period"]), None)
    by_ags = {c.ags: c for c in cities}
    missing = sorted(set(by_ags) - {p["ags"] for p in places})
    if missing:
        raise ValueError(f"cities in the vacancy index with no map position: {missing}")

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "unemployment_period": period.isoformat()[:7] if isinstance(period, date) else None,
        "vacancy_period": vacancy_period,
        "measure": "Registered vacancies per 1,000 unemployed",
        "sources": SOURCES,
        "districts": {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    d["geometry"],
                    {
                        "code": d["district_code"],
                        "name": d["district_name"],
                        "land": d["land_name"],
                        "type": d["district_type"],
                        "population": d["population"],
                        "unemployed": d["unemployed"],
                        "per_1000": _number(d["unemployed_per_1000_residents"]),
                        "change_pct": _number(d["change_since_2019_pct"]),
                    },
                )
                for d in districts
            ],
        },
        "lands": {
            "type": "FeatureCollection",
            "features": [
                _feature(land["geometry"], {"code": land["code"], "name": land["name"]})
                for land in lands
            ],
        },
        "cities": [_city(p, by_ags.get(p["ags"])) for p in places],
    }


def export_map(
    settings: Settings, out_dir: Path = MAP_DIR, index_dir: Path = INDEX_DIR
) -> list[Path]:
    vacancy_period, index = latest_index(index_dir)
    cities = read_index(index)
    with duckdb.connect(str(settings.warehouse), read_only=True) as con:
        data = build_map_data(con, cities, vacancy_period)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data.js"
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        f"// Generated by `jobease export-map`. Do not edit.\nwindow.JOBEASE_MAP = {payload};\n",
        encoding="utf-8",
    )
    return [path]
