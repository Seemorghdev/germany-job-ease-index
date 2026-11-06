"""Compare the new marts with the old v6 prototype output (one-off, for the S0 gate).

Usage: python scripts/compare_v6.py <path to v6 cities.csv>
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb

from jobease.config import load_settings

WATCH = {
    "11000000": "Berlin",
    "09162000": "München",
    "05515000": "Münster",
    "09161000": "Ingolstadt",
    "08421000": "Ulm",
    "09562000": "Erlangen",
    "09663000": "Würzburg",
}


def main(v6_csv: Path) -> int:
    with v6_csv.open(encoding="utf-8") as handle:
        old = {row["city_ags"].zfill(8): row for row in csv.DictReader(handle)}

    settings = load_settings()
    with duckdb.connect(str(settings.warehouse), read_only=True) as con:
        new_city = {
            r[0]: r
            for r in con.execute(
                "select ags, city, combined_rank, district_unemployed, is_ranked "
                "from marts.mart_city_ease"
            ).fetchall()
        }
        new_entry = dict(
            con.execute(
                "select ags, listings_per_1000_unemployed from marts.mart_city_tier_ease "
                "where tier = 'C'"
            ).fetchall()
        )
        top = con.execute(
            "select combined_rank, city from marts.mart_city_ease "
            "where is_ranked order by combined_rank limit 10"
        ).fetchall()

    print("new combined top 10:", ", ".join(f"{rank}. {city}" for rank, city in top))
    print()
    print(
        f"{'city':<12} {'v6 unemp':>9} {'new unemp':>9} {'v6 entry':>9} {'new entry':>9} "
        f"{'v6 rank':>8} {'new rank':>8} ranked"
    )
    for ags, name in WATCH.items():
        o = old.get(ags, {})
        n = new_city.get(ags)
        print(
            f"{name:<12} {o.get('unemployed', '-'):>9} {n[3] if n else '-':>9} "
            f"{o.get('jobs_C_per_1000_unemp', '-'):>9} "
            f"{new_entry.get(ags, 0) or 0:>9.1f} {o.get('combined_rank', '-'):>8} "
            f"{n[2] if n and n[2] is not None else '-':>8} {n[4] if n else '-'}"
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
