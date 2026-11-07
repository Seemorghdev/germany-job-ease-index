"""Pipeline steps. The CLI and Dagster both call these; neither holds any logic itself."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from jobease import seeds, warehouse
from jobease.config import Settings
from jobease.http import PoliteClient
from jobease.raw_store import RawArtifact, RawStore
from jobease.sources import ba_issues, ba_unemployment, bkg, destatis_gvisys
from jobease.sources.jobsuche import JobsucheClient, JobsucheError, Listing, SearchQuery

log = logging.getLogger("jobease")


@dataclass(frozen=True)
class IngestSummary:
    source: str
    rows: int
    sha256: str
    detail: dict[str, str | int]


@dataclass(frozen=True)
class City:
    ags: str
    official_name: str
    search_name: str
    population: int


@dataclass(frozen=True)
class FetchSummary:
    batch_id: str
    cities: int
    terms: int
    fetched: int
    skipped: int


def download_ba(
    settings: Settings,
    vintages: Sequence[date],
    client: PoliteClient | None = None,
) -> list[ba_issues.DownloadSummary]:
    """Download BA issues for the given reporting months into the input folder."""
    cfg = settings.ba
    with client or PoliteClient(
        min_interval_s=cfg.download_interval_s,
        max_retries=cfg.download_max_retries,
        max_backoff_s=cfg.download_max_backoff_s,
        timeout_s=120.0,
    ) as http:
        return ba_issues.download_issues(cfg, vintages, http)


def ingest_ba(settings: Settings) -> list[IngestSummary]:
    """Load every BA issue in the input folder, one landing slice per vintage.

    The folder is the source of truth: vintages whose file was removed are deleted.
    """
    cfg = settings.ba
    files = cfg.files()
    if not files:
        raise RuntimeError(f"no BA workbooks in {cfg.dir}")
    store = RawStore(settings.raw_dir)
    controls = seeds.unemployment_controls()

    parsed: list[tuple[Path, RawArtifact, ba_unemployment.ParseResult, int]] = []
    seen: dict[date, Path] = {}
    for path in files:
        artifact = store.put_file("ba_unemployment", path)
        result = ba_unemployment.parse_workbook(
            path, sheet_name=cfg.sheet, label_column=cfg.label_column, inner_suffix=cfg.inner_suffix
        )
        if result.vintage in seen:
            raise RuntimeError(
                f"{path.name} and {seen[result.vintage].name} are both the "
                f"{result.vintage:%Y-%m} issue; keep one"
            )
        seen[result.vintage] = path
        checked = ba_unemployment.check_controls(result.rows, controls)
        parsed.append((path, artifact, result, checked))

    summaries: list[IngestSummary] = []
    loaded_at = datetime.now(UTC)
    with warehouse.connect(settings.warehouse) as con:
        for path, artifact, result, checked in parsed:
            rows = [
                {
                    "vintage": result.vintage,
                    "period": r.period,
                    "district_code": r.district_code,
                    "district_label": r.district_label,
                    "unemployed": r.unemployed,
                    "value_status": r.value_status,
                    "artifact_sha256": artifact.sha256,
                    "loaded_at": loaded_at,
                }
                for r in result.rows
            ]
            warehouse.record_artifact(con, artifact)
            warehouse.replace_rows(
                con,
                "landing.ba_unemployment_monthly",
                rows,
                where="vintage = ?",
                params=[result.vintage],
            )
            detail: dict[str, str | int] = {
                "file": path.name,
                "vintage": f"{result.vintage:%Y-%m}",
                "months": f"{result.months[0]:%Y-%m}..{result.months[-1]:%Y-%m}",
                "districts": len({r.district_code for r in result.rows}),
                "suppressed": result.count("suppressed"),
                "empty": result.count("empty"),
                "zero": result.count("zero"),
                "controls_matched": checked,
            }
            log.info("ba_unemployment %s", " ".join(f"{k}={v}" for k, v in detail.items()))
            summaries.append(IngestSummary("ba_unemployment", len(rows), artifact.sha256, detail))

        stale = [
            v
            for (v,) in con.execute(
                "select distinct vintage from landing.ba_unemployment_monthly order by 1"
            ).fetchall()
            if v not in seen
        ]
        for vintage in stale:
            con.execute("delete from landing.ba_unemployment_monthly where vintage = ?", [vintage])
        if stale:
            log.info(
                "ba_unemployment: removed vintages with no file: %s",
                ", ".join(f"{v:%Y-%m}" for v in stale),
            )
    return summaries


def ingest_gvisys(settings: Settings) -> IngestSummary:
    cfg = settings.gvisys
    artifact = RawStore(settings.raw_dir).put_file("destatis_gvisys", cfg.file)
    parsed = destatis_gvisys.parse_workbook(cfg.file, sheet_name=cfg.sheet, columns=cfg.columns)
    loaded_at = datetime.now(UTC)
    municipalities = [
        {
            "edition": cfg.edition,
            "ags": m.ags,
            "name": m.name,
            "population": m.population,
            "area_km2": m.area_km2,
            "artifact_sha256": artifact.sha256,
            "loaded_at": loaded_at,
        }
        for m in parsed.municipalities
    ]
    districts = [
        {
            "edition": cfg.edition,
            "district_code": d.district_code,
            "name": d.name,
            "type_code": d.type_code,
            "artifact_sha256": artifact.sha256,
            "loaded_at": loaded_at,
        }
        for d in parsed.districts
    ]
    with warehouse.connect(settings.warehouse) as con:
        warehouse.record_artifact(con, artifact)
        warehouse.replace_rows(
            con,
            "landing.destatis_municipalities",
            municipalities,
            where="edition = ?",
            params=[cfg.edition],
        )
        warehouse.replace_rows(
            con, "landing.destatis_districts", districts, where="edition = ?", params=[cfg.edition]
        )
    log.info(
        "destatis_gvisys %s: %d municipalities, %d districts, %d excluded (no district, "
        "no population): %s",
        cfg.edition,
        len(municipalities),
        len(districts),
        len(parsed.excluded),
        "; ".join(f"{m.ags} {m.name}" for m in parsed.excluded) or "none",
    )
    return IngestSummary(
        "destatis_gvisys",
        len(municipalities),
        artifact.sha256,
        {"edition": cfg.edition, "districts": len(districts), "excluded": len(parsed.excluded)},
    )


# A sanity range for the district count: about 400 since 2011.
BKG_DISTRICTS_RANGE = (395, 405)


def ingest_bkg(settings: Settings) -> IngestSummary:
    """Load state and district boundaries and one point per municipality."""
    cfg = settings.bkg
    artifact = RawStore(settings.raw_dir).put_file("bkg_vg250", cfg.file)
    with (
        bkg.open_geopackage(cfg.file, cfg.inner_suffix) as gpkg,
        bkg.spatial_connection() as geo,
    ):

        def areas_of(layer: str, level: bkg.Level) -> list[bkg.Area]:
            return bkg.read_areas(
                geo,
                gpkg,
                layer=layer,
                level=level,
                source_crs=cfg.source_crs,
                land_area_gf=cfg.land_area_gf,
                simplify_m=cfg.simplify_m,
            )

        lands = areas_of(cfg.land_layer, "land")
        districts = areas_of(cfg.district_layer, "district")
        points = bkg.read_points(
            geo,
            gpkg,
            layer=cfg.municipality_layer,
            source_crs=cfg.source_crs,
            land_area_gf=cfg.land_area_gf,
        )
    if len(lands) != 16:
        raise bkg.GeoDataError(f"expected 16 Länder, found {len(lands)}")
    low, high = BKG_DISTRICTS_RANGE
    if not low <= len(districts) <= high:
        raise bkg.GeoDataError(f"expected {low}-{high} districts, found {len(districts)}")

    loaded_at = datetime.now(UTC)
    areas = [
        {
            "edition": cfg.edition,
            "level": a.level,
            "code": a.code,
            "name": a.name,
            "kind": a.kind,
            "area_km2": a.area_km2,
            "geometry": json.dumps(a.geometry, separators=(",", ":")),
            "simplify_m": cfg.simplify_m,
            "artifact_sha256": artifact.sha256,
            "loaded_at": loaded_at,
        }
        for a in [*lands, *districts]
    ]
    point_rows = [
        {
            "edition": cfg.edition,
            "ags": p.ags,
            "name": p.name,
            "lon": p.lon,
            "lat": p.lat,
            "artifact_sha256": artifact.sha256,
            "loaded_at": loaded_at,
        }
        for p in points
    ]
    with warehouse.connect(settings.warehouse) as con:
        warehouse.record_artifact(con, artifact)
        warehouse.replace_rows(
            con, "landing.bkg_areas", areas, where="edition = ?", params=[cfg.edition]
        )
        warehouse.replace_rows(
            con,
            "landing.bkg_municipality_points",
            point_rows,
            where="edition = ?",
            params=[cfg.edition],
        )
    detail: dict[str, str | int] = {
        "edition": cfg.edition,
        "lands": len(lands),
        "districts": len(districts),
        "municipality_points": len(points),
    }
    log.info("bkg_vg250 %s", " ".join(f"{k}={v}" for k, v in detail.items()))
    return IngestSummary("bkg_vg250", len(areas) + len(points), artifact.sha256, detail)


def cities(settings: Settings) -> list[City]:
    """Cities to query: latest Destatis edition, population at or above the threshold."""
    overrides = seeds.search_overrides()
    with warehouse.connect(settings.warehouse) as con:
        rows = con.execute(
            """
            select ags, name, population
            from landing.destatis_municipalities
            where edition = (select max(edition) from landing.destatis_municipalities)
              and population >= ?
            order by ags
            """,
            [settings.min_population],
        ).fetchall()
    if not rows:
        raise RuntimeError("no cities in the warehouse: run ingest-gvisys first")
    return [
        City(ags, name, overrides.get(ags, destatis_gvisys.search_name(name)), population)
        for ags, name, population in rows
    ]


def new_batch_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def fetch_counts(
    settings: Settings,
    *,
    batch_id: str | None = None,
    limit_cities: int | None = None,
    client_factory: Callable[[], JobsucheClient] | None = None,
) -> FetchSummary:
    """Fetch one count per (city, search term). Resumable: pass the same ``batch_id``."""
    cfg = settings.jobsuche
    batch = batch_id or new_batch_id()
    all_cities = cities(settings)
    targets = all_cities[:limit_cities] if limit_cities else all_cities
    terms = seeds.tier_terms()
    store = RawStore(settings.raw_dir)

    def make_client() -> JobsucheClient:
        return JobsucheClient(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            min_interval_s=cfg.min_interval_s,
            max_retries=cfg.max_retries,
            timeout_s=cfg.timeout_s,
        )

    fetched = skipped = 0
    total = len(targets) * len(terms)
    with warehouse.connect(settings.warehouse) as con, (client_factory or make_client)() as client:
        done = {
            (ags, tier, term)
            for ags, tier, term in con.execute(
                "select ags, tier, term from landing.jobsuche_counts where batch_id = ?", [batch]
            ).fetchall()
        }
        for city in targets:
            for item in terms:
                if (city.ags, item.tier, item.term) in done:
                    skipped += 1
                    continue
                result = client.count(
                    SearchQuery(item.term, city.search_name, cfg.radius_km, cfg.window_days)
                )
                artifact = store.put_bytes(
                    "jobsuche", result.body, suffix=".json", origin=f"jobsuche:{batch}"
                )
                warehouse.record_artifact(con, artifact)
                con.execute(
                    "insert into landing.jobsuche_counts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        batch,
                        result.fetched_at,
                        city.ags,
                        city.search_name,
                        item.tier,
                        item.term,
                        cfg.radius_km,
                        cfg.window_days,
                        result.total,
                        artifact.sha256,
                    ],
                )
                fetched += 1
                if (fetched + skipped) % 50 == 0:
                    log.info("batch %s: %d/%d", batch, fetched + skipped, total)
    log.info("batch %s complete: %d fetched, %d already present", batch, fetched, skipped)
    return FetchSummary(batch, len(targets), len(terms), fetched, skipped)


# Snapshot days follow German time: a run at 01:00 in Berlin belongs to that day.
SNAPSHOT_TZ = ZoneInfo("Europe/Berlin")
_LISTING_COLUMNS = 19


@dataclass(frozen=True)
class SnapshotSummary:
    snapshot_date: str
    cities: int
    terms: int
    fetched: int
    skipped: int
    pages: int
    listings: int
    truncated: int
    failed: int = 0  # queries still missing after every retry pass; rerun the same day

    @property
    def complete(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True)
class _QueryPages:
    total: int
    pages: int
    listings: tuple[Listing, ...]
    facets: Mapping[str, Any]
    artifacts: tuple[RawArtifact, ...]
    truncated: bool


def snapshot_date_today() -> date:
    return datetime.now(SNAPSHOT_TZ).date()


def _fetch_all_pages(
    client: JobsucheClient,
    store: RawStore,
    query: SearchQuery,
    *,
    day: date,
    size: int,
    max_pages: int,
) -> _QueryPages:
    """Page through one query. Listings that slide across a page boundary while paging
    appear twice; the first copy is kept."""
    found: dict[str, Listing] = {}
    artifacts: list[RawArtifact] = []
    total = 0
    facets: Mapping[str, Any] = {}
    page = 0
    while page < max_pages:
        page += 1
        result = client.page(query, page=page, size=size)
        artifacts.append(
            store.put_bytes("jobsuche", result.body, suffix=".json", origin=f"snapshot:{day}")
        )
        if page == 1:
            total, facets = result.total, result.facets
        for listing in result.listings:
            found.setdefault(listing.reference, listing)
        if not result.listings or page * size >= result.total:
            break
    truncated = page == max_pages and page * size < total
    return _QueryPages(total, page, tuple(found.values()), facets, tuple(artifacts), truncated)


def _listing_row(day: date, city: City, item: seeds.TierTerm, listing: Listing) -> list[object]:
    return [
        day,
        city.ags,
        item.tier,
        item.term,
        listing.reference,
        listing.title,
        listing.employer,
        listing.employer_hash,
        listing.occupation,
        listing.published_on,
        listing.changed_at,
        listing.postcode,
        listing.place,
        listing.full_time,
        listing.part_time,
        listing.marginal,
        listing.lateral_entry,
        listing.contract_duration,
        listing.pay_info,
    ]


def _store_query(
    con: duckdb.DuckDBPyConnection,
    day: date,
    city: City,
    item: seeds.TierTerm,
    radius_km: int,
    pages: _QueryPages,
) -> None:
    """Write one query and its listings in a single transaction."""
    for artifact in pages.artifacts:
        warehouse.record_artifact(con, artifact)
    con.execute("begin transaction")
    try:
        con.execute(
            "insert into landing.jobsuche_snapshot_queries "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                day,
                city.ags,
                city.search_name,
                item.tier,
                item.term,
                radius_km,
                datetime.now(UTC),
                pages.total,
                pages.pages,
                len(pages.listings),
                pages.truncated,
                json.dumps(pages.facets, ensure_ascii=False, sort_keys=True),
                pages.artifacts[0].sha256,
            ],
        )
        if pages.listings:
            con.executemany(
                "insert into landing.jobsuche_listings values "
                f"({', '.join('?' for _ in range(_LISTING_COLUMNS))})",
                [_listing_row(day, city, item, listing) for listing in pages.listings],
            )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise


def snapshot_listings(
    settings: Settings,
    *,
    snapshot_date: date | None = None,
    limit_cities: int | None = None,
    client_factory: Callable[[], JobsucheClient] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SnapshotSummary:
    """Store every open listing per (city, search term) for one day.

    Resumable: rerunning on the same day skips queries already stored. The warehouse is
    opened only for each query's write, so a long run doesn't lock it for others. Queries
    that keep failing are retried in later passes; ``failed`` counts what is still missing.
    """
    cfg = settings.jobsuche
    day = snapshot_date or snapshot_date_today()
    all_cities = cities(settings)
    targets = all_cities[:limit_cities] if limit_cities else all_cities
    terms = seeds.tier_terms()
    store = RawStore(settings.raw_dir)
    connect = partial(warehouse.connect, settings.warehouse, wait_s=cfg.snapshot_lock_wait_s)

    def make_client() -> JobsucheClient:
        return JobsucheClient(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            min_interval_s=cfg.min_interval_s,
            max_retries=cfg.max_retries,
            timeout_s=cfg.timeout_s,
        )

    with connect() as con:
        done = {
            (ags, tier, term)
            for ags, tier, term in con.execute(
                "select ags, tier, term from landing.jobsuche_snapshot_queries "
                "where snapshot_date = ?",
                [day],
            ).fetchall()
        }

    fetched = skipped = pages = listings = truncated = 0
    total_queries = len(targets) * len(terms)
    pending: list[tuple[City, seeds.TierTerm]] = []
    for city in targets:
        for item in terms:
            if (city.ags, item.tier, item.term) in done:
                skipped += 1
            else:
                pending.append((city, item))

    # A query that fails after the client's own retries is set aside, not fatal: the BA
    # server drops connections in bursts, and the next pass, after a cooldown and on a
    # fresh connection, usually gets through.
    for attempt in range(cfg.snapshot_retry_passes + 1):
        if attempt:
            log.warning(
                "snapshot %s: %d queries failed; pass %d of %d in %.0f s",
                day,
                len(pending),
                attempt,
                cfg.snapshot_retry_passes,
                cfg.snapshot_retry_cooldown_s,
            )
            sleep(cfg.snapshot_retry_cooldown_s)
        failed: list[tuple[City, seeds.TierTerm]] = []
        with (client_factory or make_client)() as client:
            for city, item in pending:
                query = SearchQuery(item.term, city.search_name, cfg.radius_km, None)
                try:
                    result = _fetch_all_pages(
                        client,
                        store,
                        query,
                        day=day,
                        size=cfg.snapshot_page_size,
                        max_pages=cfg.snapshot_max_pages,
                    )
                except JobsucheError as exc:
                    log.warning("snapshot %s: set aside: %s", day, exc)
                    failed.append((city, item))
                    continue
                with connect() as con:
                    _store_query(con, day, city, item, cfg.radius_km, result)
                fetched += 1
                pages += result.pages
                listings += len(result.listings)
                truncated += result.truncated
                if (fetched + skipped) % 50 == 0:
                    log.info(
                        "snapshot %s: %d/%d queries, %d pages, %d listings",
                        day,
                        fetched + skipped,
                        total_queries,
                        pages,
                        listings,
                    )
        pending = failed
        if not pending:
            break

    summary = SnapshotSummary(
        day.isoformat(),
        len(targets),
        len(terms),
        fetched,
        skipped,
        pages,
        listings,
        truncated,
        failed=len(pending),
    )
    if pending:
        log.error(
            "snapshot incomplete: %s; rerun today to fetch the rest: %s",
            summary,
            ", ".join(f"{city.search_name}/{item.term}" for city, item in pending),
        )
    else:
        log.info("snapshot complete: %s", summary)
    return summary
