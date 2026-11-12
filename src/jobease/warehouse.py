"""The DuckDB warehouse: landing tables written by Python, read by dbt as sources."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from jobease.raw_store import RawArtifact

log = logging.getLogger("jobease")

LANDING_DDL: tuple[str, ...] = (
    "create schema if not exists landing",
    """
    create table if not exists landing.raw_artifacts (
        source      varchar     not null,
        sha256      varchar     not null,
        path        varchar     not null,
        size_bytes  bigint      not null,
        origin      varchar     not null,
        stored_at   timestamptz not null,
        primary key (source, sha256)
    )
    """,
    """
    create table if not exists landing.ba_unemployment_monthly (
        vintage         date        not null,  -- reporting month of the issue
        period          date        not null,
        district_code   varchar     not null,
        district_label  varchar     not null,
        unemployed      integer,               -- null unless value_status = 'value'
        value_status    varchar     not null,  -- value | suppressed | empty | zero
        artifact_sha256 varchar     not null,
        loaded_at       timestamptz not null,
        primary key (vintage, period, district_code)
    )
    """,
    """
    create table if not exists landing.destatis_municipalities (
        edition         varchar     not null,
        ags             varchar     not null,
        name            varchar     not null,
        population      integer,
        area_km2        double,
        artifact_sha256 varchar     not null,
        loaded_at       timestamptz not null,
        primary key (edition, ags)
    )
    """,
    """
    create table if not exists landing.destatis_districts (
        edition         varchar     not null,
        district_code   varchar     not null,
        name            varchar     not null,
        type_code       varchar,
        artifact_sha256 varchar     not null,
        loaded_at       timestamptz not null,
        primary key (edition, district_code)
    )
    """,
    """
    create table if not exists landing.jobsuche_counts (
        batch_id        varchar     not null,
        fetched_at      timestamptz not null,
        ags             varchar     not null,
        search_name     varchar     not null,
        tier            varchar     not null,
        term            varchar     not null,
        radius_km       integer     not null,
        window_days     integer     not null,
        total           integer     not null,
        response_sha256 varchar     not null,
        primary key (batch_id, ags, tier, term)
    )
    """,
    # S2 daily snapshots. One row per (day, city, term) once all its pages are stored; its
    # listings are written in the same transaction, so a query is either complete or absent.
    """
    create table if not exists landing.jobsuche_snapshot_queries (
        snapshot_date   date        not null,
        ags             varchar     not null,
        search_name     varchar     not null,
        tier            varchar     not null,
        term            varchar     not null,
        radius_km       integer     not null,
        fetched_at      timestamptz not null,
        total           integer     not null,  -- the board's count for the query
        pages           integer     not null,
        listings        integer     not null,  -- distinct listings stored
        truncated       boolean     not null,  -- stopped at snapshot_max_pages
        facets_json     varchar     not null,  -- facet counts from page 1 (home office, ...)
        first_response_sha256 varchar not null,
        primary key (snapshot_date, ags, tier, term)
    )
    """,
    """
    create table if not exists landing.jobsuche_listings (
        snapshot_date     date      not null,
        ags               varchar   not null,
        tier              varchar   not null,
        term              varchar   not null,
        reference         varchar   not null,  -- the board's referenznummer
        title             varchar,
        employer          varchar,
        employer_hash     varchar,
        occupation        varchar,
        published_on      date,
        changed_at        timestamp,
        postcode          varchar,
        place             varchar,
        full_time         boolean,
        part_time         boolean,
        marginal          boolean,
        lateral_entry     boolean,
        contract_duration varchar,
        pay_info          varchar,
        primary key (snapshot_date, ags, tier, term, reference)
    )
    """,
    # BA "Arbeitsmarkt nach Berufen": one row per region, occupation, skill level, measure and
    # month (the reporting month and the same month a year earlier), one slice per issue.
    """
    create table if not exists landing.ba_occupation_levels (
        vintage           date        not null,  -- reporting month of the issue
        period            date        not null,
        region_code       varchar     not null,  -- DE, W, O or the 2-digit Land code
        region_name       varchar     not null,
        occupation_code   varchar     not null,  -- 'total' or the KldB 2010 code
        occupation_digits integer     not null,  -- 0 for the total
        occupation_label  varchar     not null,
        skill_level       varchar     not null,  -- total, helfer ... experte, unknown
        measure           varchar     not null,  -- unemployed, jobseekers, vacancies, ...
        value             integer,               -- null unless value_status is value or zero
        value_status      varchar     not null,  -- value | zero | suppressed | empty
        sheet             varchar     not null,
        row_number        integer     not null,
        artifact_sha256   varchar     not null,
        loaded_at         timestamptz not null,
        primary key (vintage, period, region_code, occupation_code, skill_level, measure)
    )
    """,
    # BKG boundaries, simplified and in longitude/latitude, as GeoJSON text.
    """
    create table if not exists landing.bkg_areas (
        edition         varchar     not null,
        level           varchar     not null,  -- land | district
        code            varchar     not null,  -- 2-digit Land or 5-digit district code
        name            varchar     not null,
        kind            varchar,               -- Kreisfreie Stadt, Landkreis, ...
        area_km2        double      not null,
        geometry        varchar     not null,  -- GeoJSON (Multi)Polygon, EPSG:4326
        simplify_m      double      not null,
        artifact_sha256 varchar     not null,
        loaded_at       timestamptz not null,
        primary key (edition, level, code)
    )
    """,
    """
    create table if not exists landing.bkg_municipality_points (
        edition         varchar     not null,
        ags             varchar     not null,
        name            varchar     not null,
        lon             double      not null,
        lat             double      not null,
        artifact_sha256 varchar     not null,
        loaded_at       timestamptz not null,
        primary key (edition, ags)
    )
    """,
)

# Landing tables replaced by a newer layout. Their rows came from files that are still in
# data/inputs, so the next ingest rebuilds them.
RETIRED_TABLES: tuple[str, ...] = (
    "landing.ba_unemployment",  # one month per row; replaced by ba_unemployment_monthly (S1)
)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    for statement in LANDING_DDL:
        con.execute(statement)
    for table in RETIRED_TABLES:
        con.execute(f"drop table if exists {table}")


LOCK_RETRY_S = 30.0


def _open(path: Path, wait_s: float, sleep: Callable[[float], None]) -> duckdb.DuckDBPyConnection:
    waited = 0.0
    while True:
        try:
            return duckdb.connect(str(path))
        except duckdb.IOException as exc:
            if "lock" not in str(exc).lower() or waited >= wait_s:
                raise
            log.warning("warehouse is locked by another process; retrying in %.0fs", LOCK_RETRY_S)
            sleep(LOCK_RETRY_S)
            waited += LOCK_RETRY_S


@contextmanager
def connect(
    path: Path, *, wait_s: float = 0.0, sleep: Callable[[float], None] = time.sleep
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open the warehouse. With ``wait_s``, wait that long for another process's lock
    (an open DuckDB UI, say) instead of failing at once: used by unattended runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _open(path, wait_s, sleep)
    try:
        ensure_schema(con)
        yield con
    finally:
        con.close()


def record_artifact(con: duckdb.DuckDBPyConnection, artifact: RawArtifact) -> None:
    con.execute(
        """
        insert into landing.raw_artifacts
        values (?, ?, ?, ?, ?, ?)
        on conflict (source, sha256) do nothing
        """,
        [
            artifact.source,
            artifact.sha256,
            str(artifact.path),
            artifact.size_bytes,
            artifact.origin,
            artifact.stored_at,
        ],
    )


def replace_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    where: str,
    params: Sequence[Any],
) -> int:
    """Atomically replace the slice of ``table`` selected by ``where`` with ``rows``.

    Loading the same source twice gives the same table: loads are idempotent.
    """
    if not rows:
        raise ValueError(f"refusing to replace {table} slice with zero rows")
    columns = list(rows[0])
    if any(list(row) != columns for row in rows):
        raise ValueError("all rows must have the same columns in the same order")
    placeholders = ", ".join("?" for _ in columns)
    con.execute("begin transaction")
    try:
        con.execute(f"delete from {table} where {where}", list(params))
        con.executemany(
            f"insert into {table} ({', '.join(columns)}) values ({placeholders})",
            [[row[c] for c in columns] for row in rows],
        )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    return len(rows)


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    tables = con.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'landing' order by table_name"
    ).fetchall()
    result: dict[str, int] = {}
    for (name,) in tables:
        row = con.execute(f"select count(*) from landing.{name}").fetchone()
        result[name] = int(row[0]) if row else 0
    return result
