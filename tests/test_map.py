from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import duckdb
import pytest

from jobease.map_export import build_map_data
from jobease.sources import bkg

# A unit square near Münster, counter-clockwise (the GeoJSON convention).
CCW = [[7.6, 51.9], [7.7, 51.9], [7.7, 52.0], [7.6, 52.0], [7.6, 51.9]]
HOLE_CW = [[7.62, 51.92], [7.62, 51.98], [7.68, 51.98], [7.68, 51.92], [7.62, 51.92]]


def _area(ring: list[list[float]]) -> float:
    return bkg._signed_area(ring)


def test_rewind_makes_outer_rings_clockwise_and_holes_counter_clockwise() -> None:
    polygon = bkg.rewind_for_d3({"type": "Polygon", "coordinates": [CCW, HOLE_CW]})
    outer, hole = polygon["coordinates"]
    assert _area(outer) < 0
    assert _area(hole) > 0


def test_rewind_handles_multipolygons_and_keeps_clockwise_rings() -> None:
    clockwise = CCW[::-1]
    multi = bkg.rewind_for_d3({"type": "MultiPolygon", "coordinates": [[CCW], [clockwise]]})
    assert all(_area(p[0]) < 0 for p in multi["coordinates"])
    assert multi["coordinates"][1][0] == clockwise


def test_round_coordinates() -> None:
    rounded = bkg.round_coordinates(
        {"type": "Polygon", "coordinates": [[[7.123456, 51.987654], [7.1, 51.9]]]}
    )
    assert rounded["coordinates"] == [[[7.1235, 51.9877], [7.1, 51.9]]]


def test_swapped_axes_are_caught() -> None:
    swapped = {"type": "Polygon", "coordinates": [[[lat, lon] for lon, lat in CCW]]}
    with pytest.raises(bkg.GeoDataError, match="swapped"):
        bkg.check_extent(swapped, "05515 Münster")
    bkg.check_extent({"type": "Polygon", "coordinates": [CCW]}, "05515 Münster")


def test_points_and_lines_are_rejected() -> None:
    with pytest.raises(bkg.GeoDataError, match="Polygon"):
        bkg.rewind_for_d3({"type": "Point", "coordinates": [7.6, 51.9]})


def test_open_geopackage_extracts_the_single_gpkg(tmp_path: Path) -> None:
    archive = tmp_path / "vg250.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("vg250_01-01.utm32s.gpkg.ebenen/DE_VG250.gpkg", b"gpkg bytes")
        z.writestr("vg250_01-01.utm32s.gpkg.ebenen/README.txt", b"readme")
    with bkg.open_geopackage(archive, ".gpkg") as gpkg:
        assert gpkg.read_bytes() == b"gpkg bytes"
    assert not gpkg.exists()  # cleaned up afterwards


def test_open_geopackage_needs_exactly_one(tmp_path: Path) -> None:
    archive = tmp_path / "vg250.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.gpkg", b"1")
        z.writestr("b.gpkg", b"2")
    with (
        pytest.raises(bkg.GeoDataError, match="expected one"),
        bkg.open_geopackage(archive, ".gpkg"),
    ):
        pass


# --- the map export -----------------------------------------------------------------


def _warehouse() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    square = json.dumps({"type": "Polygon", "coordinates": [CCW]})
    con.execute("create schema marts; create schema staging")
    con.execute(
        """
        create table marts.mart_district_map as select
            '05515' as district_code, 'Münster, Stadt' as district_name,
            'Nordrhein-Westfalen' as land_name, 'Kreisfreie Stadt' as district_type,
            320000 as population, 8957 as unemployed, 27.99 as unemployed_per_1000_residents,
            12.345 as change_since_2019_pct, date '2026-10-01' as unemployment_period,
            ? as geometry
        """,
        [square],
    )
    con.execute(
        "create table staging.stg_bkg__areas as select 'land' as level, '05' as code, "
        "'Nordrhein-Westfalen' as name, ? as geometry",
        [square],
    )
    con.execute(
        """
        create table marts.mart_city_map as select
            '05515000' as ags, 'Münster' as city, 320000 as population, true as is_ranked,
            4 as combined_rank, 7.62571 as lon, 51.96236 as lat,
            12.04 as rate_a, 20.5 as rate_b, 60.25 as rate_c
        """
    )
    return con


def test_map_data_is_rewound_rounded_and_aggregate_only() -> None:
    data: dict[str, Any] = build_map_data(_warehouse())

    assert data["unemployment_period"] == "2026-10"
    [district] = data["districts"]["features"]
    assert district["properties"] == {
        "code": "05515",
        "name": "Münster, Stadt",
        "land": "Nordrhein-Westfalen",
        "type": "Kreisfreie Stadt",
        "population": 320000,
        "unemployed": 8957,
        "per_1000": 28.0,
        "change_pct": 12.3,
    }
    assert _area(district["geometry"]["coordinates"][0]) < 0  # rewound for d3
    [city] = data["cities"]
    assert city["rates"] == {"A": 12.0, "B": 20.5, "C": 60.2}
    assert (city["lon"], city["lat"]) == (7.6257, 51.9624)
    assert set(data["tiers"]) == {"A", "B", "C"}
    assert any("BKG" in s for s in data["sources"])


def test_map_data_has_no_listing_fields() -> None:
    text = json.dumps(build_map_data(_warehouse()), default=str)
    for private in ("reference", "employer", "title", "referenznummer"):
        assert private not in text


def test_period_is_none_without_districts() -> None:
    con = _warehouse()
    con.execute("delete from marts.mart_district_map")
    assert build_map_data(con)["unemployment_period"] is None
