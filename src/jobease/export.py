"""Export the marts as reviewed, publishable files: aggregates only, no listing-level data."""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from jobease import seeds
from jobease.config import Settings

CITY_COLUMNS = (
    "ags",
    "city",
    "population",
    "district_code",
    "district_name",
    "district_type",
    "district_coverage",
    "district_unemployed",
    "unemployment_period",
    "is_ranked",
    "not_ranked_reason",
    "combined_score",
    "combined_rank",
)
TIER_COLUMNS = ("listings", "listings_per_1000_unemployed", "tier_rank")
REFERENCE_CITIES = ("11000000", "02000000", "09162000")  # Berlin, Hamburg, München
TOP_N = 15


def _json_default(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def _records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _top_by(rows: list[dict[str, Any]], rank_column: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: int(row[rank_column]))[:TOP_N]


def export(settings: Settings) -> list[Path]:
    tiers = seeds.tiers()
    with duckdb.connect(str(settings.warehouse), read_only=True) as con:
        cities = _records(
            con, f"select {', '.join(CITY_COLUMNS)} from marts.mart_city_ease order by ags"
        )
        tier_rows = _records(
            con,
            "select ags, tier, batch_id, "
            + ", ".join(TIER_COLUMNS)
            + " from marts.mart_city_tier_ease",
        )

    by_city: dict[str, dict[str, Any]] = {c["ags"]: dict(c) for c in cities}
    batches = {r["batch_id"] for r in tier_rows if r["batch_id"]}
    for row in tier_rows:
        slug = tiers[row["tier"]].slug
        for column in TIER_COLUMNS:
            by_city[row["ags"]][f"{slug}_{column}"] = row[column]

    wide = sorted(
        by_city.values(), key=lambda c: (c["combined_rank"] is None, c["combined_rank"], c["ags"])
    )
    out = settings.exports_dir
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "city_ease.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(wide[0]))
        writer.writeheader()
        writer.writerows(wide)

    ranked = [c for c in wide if c["is_ranked"]]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "unemployment_period": str(ranked[0]["unemployment_period"])[:7] if ranked else None,
        "jobsuche_batches": sorted(batches),
        "tiers": {
            t.code: {"label": t.label, "slug": t.slug, "weight": t.weight} for t in tiers.values()
        },
        "ranked_cities": len(ranked),
        "not_ranked": [
            {"ags": c["ags"], "city": c["city"], "reason": c["not_ranked_reason"]}
            for c in wide
            if not c["is_ranked"]
        ],
        "combined_top": ranked[:TOP_N],
        "tier_top": {t.slug: _top_by(ranked, f"{t.slug}_tier_rank") for t in tiers.values()},
        "reference_cities": [by_city[a] for a in REFERENCE_CITIES if a in by_city],
    }
    json_path = out / "summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return [csv_path, json_path]
