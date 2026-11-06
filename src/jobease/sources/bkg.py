"""BKG Verwaltungsgebiete (VG250): state and district boundaries, municipality points.

The GeoPackage ships in a ZIP, in UTM zone 32 (metres). It is read with DuckDB's spatial
extension in a throwaway in-memory database: shapes are merged per official code,
simplified for web maps, reprojected to longitude/latitude and stored as GeoJSON text.
The warehouse never needs the extension.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import duckdb

# Germany's extent with a margin. A point outside means swapped axes or a wrong CRS.
LON_RANGE = (5.0, 16.0)
LAT_RANGE = (47.0, 55.5)

Level = Literal["land", "district"]
CODE_LENGTH: dict[Level, int] = {"land": 2, "district": 5}


class GeoDataError(ValueError):
    """The boundary file isn't what we expect."""


@dataclass(frozen=True)
class Area:
    level: Level
    code: str
    name: str
    kind: str | None
    area_km2: float
    geometry: dict[str, Any]


@dataclass(frozen=True)
class Point:
    ags: str
    name: str
    lon: float
    lat: float


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


@contextmanager
def open_geopackage(zip_path: Path, inner_suffix: str) -> Iterator[Path]:
    """Extract the single GeoPackage from the ZIP into a temporary folder."""
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(inner_suffix.lower())]
        if len(names) != 1:
            raise GeoDataError(f"{zip_path.name}: expected one *{inner_suffix}, found {names}")
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(archive.extract(names[0], tmp))


def spatial_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("install spatial")  # downloads the extension once, then uses the cache
    con.execute("load spatial")
    return con


def layers(con: duckdb.DuckDBPyConnection, gpkg: Path) -> list[dict[str, Any]]:
    """Layer names, feature counts and field names, to confirm a layout by eye."""
    rows = con.execute(f"select layers from ST_Read_Meta({_quote(str(gpkg))})").fetchall()
    out: list[dict[str, Any]] = []
    for (meta,) in rows:
        for layer in meta:
            out.append(
                {
                    "name": layer["name"],
                    "features": layer["feature_count"],
                    "fields": [f["name"] for f in layer["fields"]],
                }
            )
    return out


def geofactor_counts(con: duckdb.DuckDBPyConnection, gpkg: Path, layer: str) -> dict[int, int]:
    rows = con.execute(
        f"select GF, count(*) from ST_Read({_quote(str(gpkg))}, layer={_quote(layer)}) "
        "group by 1 order by 1"
    ).fetchall()
    return {int(gf): int(n) for gf, n in rows}


def _gf_list(land_area_gf: Sequence[int]) -> str:
    if not land_area_gf:
        raise GeoDataError("land_area_gf is empty")
    return ", ".join(str(int(gf)) for gf in land_area_gf)


def read_areas(
    con: duckdb.DuckDBPyConnection,
    gpkg: Path,
    *,
    layer: str,
    level: Level,
    source_crs: str,
    land_area_gf: Sequence[int],
    simplify_m: float,
) -> list[Area]:
    length = CODE_LENGTH[level]
    sql = f"""
        with parts as (
            select left(AGS, {length}) as code, GEN as name, BEZ as kind, geom
            from ST_Read({_quote(str(gpkg))}, layer={_quote(layer)})
            where GF in ({_gf_list(land_area_gf)})
        ),
        merged as (
            select code, any_value(name) as name, any_value(kind) as kind,
                   ST_Union_Agg(geom) as geom
            from parts
            group by code
        )
        select
            code,
            name,
            kind,
            ST_Area(geom) / 1e6 as area_km2,
            ST_AsGeoJSON(
                ST_Transform(
                    ST_SimplifyPreserveTopology(geom, {float(simplify_m)}),
                    {_quote(source_crs)}, 'EPSG:4326', true
                )
            ) as geometry
        from merged
        order by code
    """
    areas = [
        Area(level, str(code), str(name), kind, float(area), json.loads(geometry))
        for code, name, kind, area, geometry in con.execute(sql).fetchall()
    ]
    if not areas:
        raise GeoDataError(f"layer {layer!r} has no land areas (GF in {list(land_area_gf)})")
    for area in areas:
        if len(area.code) != length or not area.code.isdigit():
            raise GeoDataError(f"{layer}: bad code {area.code!r} for {area.name}")
        check_extent(area.geometry, f"{area.code} {area.name}")
    return areas


def read_points(
    con: duckdb.DuckDBPyConnection,
    gpkg: Path,
    *,
    layer: str,
    source_crs: str,
    land_area_gf: Sequence[int],
) -> list[Point]:
    """One point inside every municipality (not the centroid, which can fall outside)."""
    sql = f"""
        with merged as (
            select AGS as ags, any_value(GEN) as name, ST_Union_Agg(geom) as geom
            from ST_Read({_quote(str(gpkg))}, layer={_quote(layer)})
            where GF in ({_gf_list(land_area_gf)})
            group by AGS
        ),
        points as (
            select ags, name,
                   ST_Transform(
                       ST_PointOnSurface(geom), {_quote(source_crs)}, 'EPSG:4326', true
                   ) as p
            from merged
        )
        select ags, name, ST_X(p), ST_Y(p) from points order by ags
    """
    points = [
        Point(str(ags), str(name), float(lon), float(lat))
        for ags, name, lon, lat in con.execute(sql).fetchall()
    ]
    for point in points:
        if len(point.ags) != 8 or not point.ags.isdigit():
            raise GeoDataError(f"{layer}: bad AGS {point.ags!r} for {point.name}")
        _check_position(point.lon, point.lat, f"{point.ags} {point.name}")
    return points


# --- geometry helpers, pure Python -----------------------------------------------------


def _positions(geometry: dict[str, Any]) -> Iterator[Sequence[float]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        for ring in coordinates or []:
            yield from ring
    elif kind == "MultiPolygon":
        for polygon in coordinates or []:
            for ring in polygon:
                yield from ring
    else:
        raise GeoDataError(f"expected a (Multi)Polygon, got {kind!r}")


def _check_position(lon: float, lat: float, label: str) -> None:
    if not (LON_RANGE[0] <= lon <= LON_RANGE[1] and LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        raise GeoDataError(
            f"{label}: position ({lon:.3f}, {lat:.3f}) is outside Germany; "
            "are longitude and latitude swapped, or is source_crs wrong?"
        )


def check_extent(geometry: dict[str, Any], label: str) -> None:
    for position in _positions(geometry):
        _check_position(position[0], position[1], label)


def _signed_area(ring: Sequence[Sequence[float]]) -> float:
    """Shoelace area in square degrees: positive for counter-clockwise rings."""
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in pairwise(ring))


def _orient(ring: list[list[float]], *, clockwise: bool) -> list[list[float]]:
    is_clockwise = _signed_area(ring) < 0
    return ring if is_clockwise == clockwise else ring[::-1]


def rewind_for_d3(geometry: dict[str, Any]) -> dict[str, Any]:
    """d3-geo draws on a sphere and reads a counter-clockwise ring as "everything except
    this area", filling the whole globe. GeoJSON (RFC 7946) prefers counter-clockwise, so
    rings are flipped here: outer rings clockwise, holes counter-clockwise."""

    def polygon(rings: list[list[list[float]]]) -> list[list[list[float]]]:
        return [_orient(ring, clockwise=(i == 0)) for i, ring in enumerate(rings)]

    kind = geometry.get("type")
    if kind == "Polygon":
        return {"type": kind, "coordinates": polygon(geometry["coordinates"])}
    if kind == "MultiPolygon":
        return {"type": kind, "coordinates": [polygon(p) for p in geometry["coordinates"]]}
    raise GeoDataError(f"expected a (Multi)Polygon, got {kind!r}")


def round_coordinates(geometry: dict[str, Any], digits: int = 4) -> dict[str, Any]:
    """Four decimals of a degree is about 10 m: plenty for a national map, and it cuts
    the file size by more than half."""

    def ring(points: list[list[float]]) -> list[list[float]]:
        return [[round(p[0], digits), round(p[1], digits)] for p in points]

    kind = geometry.get("type")
    if kind == "Polygon":
        return {"type": kind, "coordinates": [ring(r) for r in geometry["coordinates"]]}
    if kind == "MultiPolygon":
        return {
            "type": kind,
            "coordinates": [[ring(r) for r in p] for p in geometry["coordinates"]],
        }
    raise GeoDataError(f"expected a (Multi)Polygon, got {kind!r}")
