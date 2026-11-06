from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jobease import seeds, warehouse
from jobease.raw_store import RawStore


def test_raw_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    first = store.put_bytes("jobsuche", b'{"a": 1}', suffix=".json", origin="test")
    second = store.put_bytes("jobsuche", b'{"a": 1}', suffix=".json", origin="test")
    assert first.path == second.path
    assert first.path.read_bytes() == b'{"a": 1}'
    assert first.path.name == f"{first.sha256}.json"


@pytest.mark.parametrize("source", ["", "../escape", ".hidden", "a/b"])
def test_raw_store_rejects_unsafe_source_names(tmp_path: Path, source: str) -> None:
    with pytest.raises(ValueError):
        RawStore(tmp_path).put_bytes(source, b"x", suffix=".bin", origin="test")


def _row(code: str, unemployed: int) -> dict[str, object]:
    return {
        "vintage": date(2026, 10, 1),
        "period": date(2026, 10, 1),
        "district_code": code,
        "district_label": code,
        "unemployed": unemployed,
        "value_status": "value",
        "artifact_sha256": "abc",
        "loaded_at": datetime.now(UTC),
    }


def test_replace_rows_is_idempotent(tmp_path: Path) -> None:
    with warehouse.connect(tmp_path / "w.duckdb") as con:
        for _ in range(2):
            warehouse.replace_rows(
                con,
                "landing.ba_unemployment_monthly",
                [_row("11000", 1), _row("05515", 2)],
                where="vintage = ?",
                params=[date(2026, 10, 1)],
            )
        assert warehouse.table_counts(con)["ba_unemployment_monthly"] == 2


def test_replace_rows_rolls_back_on_failure(tmp_path: Path) -> None:
    with warehouse.connect(tmp_path / "w.duckdb") as con:
        warehouse.replace_rows(
            con,
            "landing.ba_unemployment_monthly",
            [_row("11000", 1)],
            where="vintage = ?",
            params=[date(2026, 10, 1)],
        )
        bad = [_row("05515", 2), _row("05515", 3)]  # duplicate primary key
        with pytest.raises(Exception):  # noqa: B017 - any DuckDB constraint error
            warehouse.replace_rows(
                con,
                "landing.ba_unemployment_monthly",
                bad,
                where="vintage = ?",
                params=[date(2026, 10, 1)],
            )
        assert warehouse.table_counts(con)["ba_unemployment_monthly"] == 1


def test_replace_rows_refuses_empty_slice(tmp_path: Path) -> None:
    with warehouse.connect(tmp_path / "w.duckdb") as con, pytest.raises(ValueError):
        warehouse.replace_rows(con, "landing.ba_unemployment_monthly", [], where="true", params=[])


def test_shipped_seeds_are_consistent() -> None:
    tiers = seeds.tiers()
    terms = seeds.tier_terms()
    assert set(tiers) == {t.tier for t in terms}
    assert all(t.weight > 0 for t in tiers.values())
    assert seeds.unemployment_controls()[(date(2026, 10, 1), "11000")] == 223_254
    seeds.search_overrides()  # validates AGS format
