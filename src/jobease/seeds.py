"""Reference data shared by Python and dbt.

The CSV files in ``dbt/seeds`` are the single source of truth: dbt loads them as seeds,
and the fetchers read the same files here. A search term or control figure is defined once.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from jobease.config import SEEDS_DIR, parse_period


class SeedError(ValueError):
    """A seed file is malformed or inconsistent with another seed."""


@dataclass(frozen=True)
class Tier:
    code: str
    label: str
    slug: str
    weight: float


@dataclass(frozen=True)
class TierTerm:
    tier: str
    term: str


def _read(name: str, seeds_dir: Path = SEEDS_DIR) -> list[dict[str, str]]:
    path = seeds_dir / f"{name}.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return [{k: v.strip() for k, v in row.items()} for row in csv.DictReader(handle)]


@cache
def tiers(seeds_dir: Path = SEEDS_DIR) -> dict[str, Tier]:
    result: dict[str, Tier] = {}
    for row in _read("tiers", seeds_dir):
        tier = Tier(row["tier"], row["label"], row["slug"], float(row["weight"]))
        if tier.code in result:
            raise SeedError(f"duplicate tier {tier.code!r} in tiers.csv")
        if tier.weight <= 0:
            raise SeedError(f"tier {tier.code!r} must have a positive weight")
        result[tier.code] = tier
    return result


@cache
def tier_terms(seeds_dir: Path = SEEDS_DIR) -> tuple[TierTerm, ...]:
    known = tiers(seeds_dir)
    seen: set[tuple[str, str]] = set()
    result: list[TierTerm] = []
    for row in _read("tier_terms", seeds_dir):
        item = TierTerm(row["tier"], row["term"])
        if item.tier not in known:
            raise SeedError(f"tier_terms.csv uses unknown tier {item.tier!r}")
        if not item.term:
            raise SeedError(f"empty search term for tier {item.tier!r}")
        key = (item.tier, item.term.casefold())
        if key in seen:
            raise SeedError(f"duplicate term {item.term!r} in tier {item.tier!r}")
        seen.add(key)
        result.append(item)
    missing = set(known) - {t.tier for t in result}
    if missing:
        raise SeedError(f"tiers without search terms: {sorted(missing)}")
    return tuple(result)


@cache
def search_overrides(seeds_dir: Path = SEEDS_DIR) -> dict[str, str]:
    """AGS -> the place name the job board understands, where the official name doesn't work."""
    result: dict[str, str] = {}
    for row in _read("city_search_overrides", seeds_dir):
        ags = row["ags"]
        if len(ags) != 8 or not ags.isdigit():
            raise SeedError(f"city_search_overrides.csv: AGS must be 8 digits, got {ags!r}")
        result[ags] = row["search_name"]
    return result


@cache
def unemployment_controls(seeds_dir: Path = SEEDS_DIR) -> dict[tuple[date, str], int]:
    """(period, district code) -> unemployed count published by the BA in a press release."""
    result: dict[tuple[date, str], int] = {}
    for row in _read("controls_unemployment", seeds_dir):
        period = parse_period(row["period"][:7])
        result[(period, row["district_code"])] = int(row["unemployed"])
    return result
