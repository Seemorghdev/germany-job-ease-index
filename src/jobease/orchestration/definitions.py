"""Dagster definitions: Python assets land raw data, dbt builds everything downstream.

Run ``make dev`` to open the asset graph. Every asset calls one function in
``jobease.pipeline`` or one dbt command; there is no logic here.
"""

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from jobease import pipeline, vacancy_export
from jobease.config import DBT_DIR, load_settings
from jobease.official_vacancies import refresh_index

SETTINGS = load_settings()
os.environ.setdefault("JOBEASE_DUCKDB", str(SETTINGS.warehouse))

DBT_PROJECT = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
DBT_PROJECT.prepare_if_dev()

# Use the dbt installed next to this interpreter, so the venv needn't be on PATH.
_VENV_DBT = Path(sys.executable).with_name("dbt")
DBT_EXECUTABLE = str(_VENV_DBT) if _VENV_DBT.exists() else (shutil.which("dbt") or "dbt")

LANDING = "landing"
LANDING_KINDS = {"python", "duckdb"}


def _key(table: str) -> dg.AssetKey:
    return dg.AssetKey([LANDING, table])


@dg.asset(key=_key("ba_unemployment_monthly"), group_name=LANDING, kinds=LANDING_KINDS)
def ba_unemployment() -> dg.MaterializeResult[None]:
    """Unemployed people per district and month, from every BA issue in the input folder."""
    summaries = pipeline.ingest_ba(SETTINGS)
    return dg.MaterializeResult(
        metadata={
            "rows": sum(s.rows for s in summaries),
            "vintages": [str(s.detail["vintage"]) for s in summaries],
            "controls_matched": sum(int(s.detail["controls_matched"]) for s in summaries),
        }
    )


@dg.multi_asset(
    specs=[
        dg.AssetSpec(_key("destatis_municipalities"), group_name=LANDING, kinds=LANDING_KINDS),
        dg.AssetSpec(_key("destatis_districts"), group_name=LANDING, kinds=LANDING_KINDS),
    ]
)
def destatis_gvisys() -> Iterator[dg.MaterializeResult[None]]:
    """Municipalities and districts with official codes and population (Destatis GV-ISys)."""
    summary = pipeline.ingest_gvisys(SETTINGS)
    yield dg.MaterializeResult(
        asset_key=_key("destatis_municipalities"),
        metadata={"rows": summary.rows, "sha256": summary.sha256},
    )
    yield dg.MaterializeResult(
        asset_key=_key("destatis_districts"),
        metadata={"rows": summary.detail["districts"], "sha256": summary.sha256},
    )


@dg.multi_asset(
    specs=[
        dg.AssetSpec(_key("bkg_areas"), group_name=LANDING, kinds=LANDING_KINDS),
        dg.AssetSpec(_key("bkg_municipality_points"), group_name=LANDING, kinds=LANDING_KINDS),
    ]
)
def bkg_vg250() -> Iterator[dg.MaterializeResult[None]]:
    """State and district boundaries and municipality points (BKG VG250, 1 January)."""
    summary = pipeline.ingest_bkg(SETTINGS)
    yield dg.MaterializeResult(
        asset_key=_key("bkg_areas"),
        metadata={
            "districts": summary.detail["districts"],
            "lands": summary.detail["lands"],
            "sha256": summary.sha256,
        },
    )
    yield dg.MaterializeResult(
        asset_key=_key("bkg_municipality_points"),
        metadata={"rows": summary.detail["municipality_points"], "sha256": summary.sha256},
    )


@dg.asset(key=_key("ba_occupation_levels"), group_name=LANDING, kinds=LANDING_KINDS)
def ba_occupations() -> dg.MaterializeResult[None]:
    """Unemployed and vacancies by occupation and skill level, Germany and Länder (BA)."""
    summaries = pipeline.ingest_occupations(SETTINGS)
    return dg.MaterializeResult(
        metadata={
            "rows": sum(s.rows for s in summaries),
            "vintages": [str(s.detail["vintage"]) for s in summaries],
        }
    )


@dg.asset(
    key=_key("jobsuche_counts"),
    group_name=LANDING,
    kinds=LANDING_KINDS,
    deps=[_key("destatis_municipalities")],
)
def jobsuche_counts() -> dg.MaterializeResult[None]:
    """One listing count per city and search term from the BA job board (~20-30 min)."""
    summary = pipeline.fetch_counts(SETTINGS)
    return dg.MaterializeResult(
        metadata={
            "batch_id": summary.batch_id,
            "cities": summary.cities,
            "terms": summary.terms,
            "fetched": summary.fetched,
        }
    )


@dg.multi_asset(
    specs=[
        dg.AssetSpec(
            _key("jobsuche_snapshot_queries"),
            group_name=LANDING,
            kinds=LANDING_KINDS,
            deps=[_key("destatis_municipalities")],
        ),
        dg.AssetSpec(_key("jobsuche_listings"), group_name=LANDING, kinds=LANDING_KINDS),
    ]
)
def jobsuche_snapshot() -> Iterator[dg.MaterializeResult[None]]:
    """Every open listing per city and search term, for today (private, never exported)."""
    summary = pipeline.snapshot_listings(SETTINGS)
    if not summary.complete:
        raise dg.Failure(
            f"{summary.failed} snapshot queries still failing after every retry pass; "
            "rerun the asset today to fetch them"
        )
    yield dg.MaterializeResult(
        asset_key=_key("jobsuche_snapshot_queries"),
        metadata={
            "snapshot_date": summary.snapshot_date,
            "truncated": summary.truncated,
            "queries": summary.fetched + summary.skipped,
            "pages": summary.pages,
        },
    )
    yield dg.MaterializeResult(
        asset_key=_key("jobsuche_listings"),
        metadata={
            "snapshot_date": summary.snapshot_date,
            "truncated": summary.truncated,
            "listings": summary.listings,
        },
    )


@dbt_assets(manifest=DBT_PROJECT.manifest_path, project=DBT_PROJECT)
def jobease_dbt(context: dg.AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
    yield from dbt.cli(["build"], context=context).stream()


@dg.asset(group_name="exports", kinds={"python"}, deps=[_key("official_vacancy_index")])
def city_ease_exports() -> dg.MaterializeResult[None]:
    """Publishable aggregates from the official vacancy index: data/exports/*.

    The job-board marts are never exported: the Jobbörse terms forbid automated collection.
    """
    paths = vacancy_export.export_vacancies()
    return dg.MaterializeResult(metadata={"files": [str(p) for p in paths]})


@dg.asset(key=_key("official_vacancy_index"), group_name="official_statistics", kinds={"python"})
def official_vacancy_index() -> dg.MaterializeResult[None]:
    """Fetch the BA Kreis vacancy CSVs and write the separate local official index."""
    summary = refresh_index(SETTINGS)
    return dg.MaterializeResult(
        metadata={
            "period": str(summary.period),
            "geographies": summary.geographies,
            "vacancy_csvs": summary.vacancy_csvs,
            "included": summary.included,
            "excluded": summary.excluded,
            "index": str(summary.index),
        }
    )


refresh_all = dg.define_asset_job("refresh_all", selection=dg.AssetSelection.all())
rebuild_from_landing = dg.define_asset_job(
    "rebuild_from_landing",
    selection=dg.AssetSelection.all() - dg.AssetSelection.groups(LANDING),
)
daily_snapshot = dg.define_asset_job(
    "daily_snapshot",
    selection=dg.AssetSelection.assets(jobsuche_snapshot).downstream(),
)
# Off by default: launchd (`jobease launchd-plist`) runs the snapshot without a Dagster
# process staying up. Turn this on instead when Dagster runs as a daemon.
daily_snapshot_schedule = dg.ScheduleDefinition(
    job=daily_snapshot,
    cron_schedule="0 9 * * *",
    execution_timezone="Europe/Berlin",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)
official_vacancy_refresh_job = dg.define_asset_job(
    "official_vacancy_refresh",
    selection=dg.AssetSelection.assets(official_vacancy_index),
)
official_vacancy_refresh_schedule = dg.ScheduleDefinition(
    job=official_vacancy_refresh_job,
    cron_schedule="0 10 5 * *",
    execution_timezone="Europe/Berlin",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)

defs = dg.Definitions(
    assets=[
        ba_unemployment,
        destatis_gvisys,
        bkg_vg250,
        ba_occupations,
        jobsuche_counts,
        jobsuche_snapshot,
        official_vacancy_index,
        jobease_dbt,
        city_ease_exports,
    ],
    jobs=[refresh_all, rebuild_from_landing, daily_snapshot, official_vacancy_refresh_job],
    schedules=[daily_snapshot_schedule, official_vacancy_refresh_schedule],
    resources={"dbt": DbtCliResource(project_dir=DBT_PROJECT, dbt_executable=DBT_EXECUTABLE)},
)
