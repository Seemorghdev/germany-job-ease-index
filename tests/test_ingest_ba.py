from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import write_xlsx, zip_one
from jobease import pipeline, warehouse
from jobease.config import Settings, load_settings


def _settings(tmp_path: Path) -> Settings:
    base = load_settings()
    return replace(
        base,
        warehouse=tmp_path / "w.duckdb",
        raw_dir=tmp_path / "raw",
        ba=replace(base.ba, dir=tmp_path / "ba"),
    )


def _issue(folder: Path, name: str, rows: list[list[object]]) -> Path:
    folder.mkdir(exist_ok=True)
    inner = write_xlsx(folder.parent / f"{name}.xlsx", {"Übersicht_Kreise": rows})
    return zip_one(folder / f"{name}.zip", f"{name}_Arbeitslose.xlsx", inner.read_bytes())


def _september_issue(ba_rows: list[list[object]]) -> list[list[object]]:
    rows = [list(r) for r in ba_rows]
    for row in rows[5:]:
        row[6] = 0  # October not reported yet
    return rows


def _vintages(settings: Settings) -> list[str]:
    with warehouse.connect(settings.warehouse) as con:
        rows = con.execute(
            "select distinct strftime(vintage, '%Y-%m') from landing.ba_unemployment_monthly "
            "order by 1"
        ).fetchall()
    return [r[0] for r in rows]


def test_loads_every_issue_in_the_folder(tmp_path: Path, ba_rows: list[list[object]]) -> None:
    settings = _settings(tmp_path)
    _issue(settings.ba.dir, "202609", _september_issue(ba_rows))
    _issue(settings.ba.dir, "202610", ba_rows)

    summaries = pipeline.ingest_ba(settings)

    assert [s.detail["vintage"] for s in summaries] == ["2026-09", "2026-10"]
    assert [s.detail["controls_matched"] for s in summaries] == [0, 4]
    assert _vintages(settings) == ["2026-09", "2026-10"]


def test_removed_file_removes_its_vintage(tmp_path: Path, ba_rows: list[list[object]]) -> None:
    settings = _settings(tmp_path)
    september = _issue(settings.ba.dir, "202609", _september_issue(ba_rows))
    _issue(settings.ba.dir, "202610", ba_rows)
    pipeline.ingest_ba(settings)

    september.unlink()
    pipeline.ingest_ba(settings)

    assert _vintages(settings) == ["2026-10"]


def test_two_files_for_the_same_month_fail(tmp_path: Path, ba_rows: list[list[object]]) -> None:
    settings = _settings(tmp_path)
    _issue(settings.ba.dir, "a", ba_rows)
    _issue(settings.ba.dir, "b", ba_rows)
    with pytest.raises(RuntimeError, match="both the 2026-10 issue"):
        pipeline.ingest_ba(settings)


def test_retired_landing_table_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
    with warehouse.connect(path) as con:
        con.execute("create table landing.ba_unemployment (x integer)")
    with warehouse.connect(path) as con:
        assert "ba_unemployment" not in warehouse.table_counts(con)
