"""Shared bits for the showcase notebooks in ``notebooks/``.

Notebooks read only the publishable marts (see ``PUBLISHABLE``); the listing-level
tables stay private. ``tests/test_notebooks.py`` enforces that.
"""

from __future__ import annotations

from typing import Any

import duckdb

from jobease.config import load_settings

# One colour per tier, used by every chart, so a tier looks the same everywhere.
TIER_COLORS = {"A": "#4C78A8", "B": "#F58518", "C": "#54A24B"}

# Relations a notebook may read. Everything here is an aggregate or public BA/Destatis data.
PUBLISHABLE = frozenset(
    {
        "marts.mart_city_ease",
        "marts.mart_city_tier_ease",
        "marts.mart_city_listing_profile",
        "marts.mart_tier_lifetimes",
        "marts.mart_district_map",
        "marts.mart_city_map",
        "marts.fct_unemployment_monthly",
        "marts.dim_date",
        "marts.dim_district",
        "reference.tiers",
        "reference.district_changes",
    }
)


def connect() -> duckdb.DuckDBPyConnection:
    """A read-only connection: several notebooks can share the warehouse at once. A writer
    (ingest, build, the daily snapshot) still needs it to themselves, briefly."""
    return duckdb.connect(str(load_settings().warehouse), read_only=True)


def row(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[Any, ...]:
    """The single row a query returns. Runs the query once, as a statement: DuckDB
    relations (``con.sql``) re-run on every fetch and no longer offer ``fetchone``."""
    rows = con.execute(sql).fetchall()
    if len(rows) != 1:
        raise ValueError(f"expected one row, got {len(rows)}: {sql}")
    return tuple(rows[0])


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    """The single value a query returns."""
    values = row(con, sql)
    if len(values) != 1:
        raise ValueError(f"expected one column, got {len(values)}: {sql}")
    return values[0]


def column(con: duckdb.DuckDBPyConnection, sql: str) -> list[Any]:
    """The first column of every row a query returns."""
    return [r[0] for r in con.execute(sql).fetchall()]
