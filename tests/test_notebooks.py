"""Published notebooks (level 2) may only read publishable relations: never listing-level
data. Level-1 lessons may read anything, so they must never be exported."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from jobease.config import DBT_DIR, REPO_ROOT
from jobease.showcase import PUBLISHABLE, column, row, scalar

NOTEBOOKS = sorted((REPO_ROOT / "notebooks" / "level2_analysis").glob("*.py"))
LESSONS = sorted((REPO_ROOT / "notebooks" / "level1_learn").glob("*.py"))
SCHEMAS = "landing|staging|intermediate|marts|reference|main"
RELATION = re.compile(rf"\b({SCHEMAS})\.([a-z_][a-z0-9_]*)\b")


def test_there_are_notebooks() -> None:
    assert NOTEBOOKS


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_reads_only_publishable_relations(notebook: Path) -> None:
    used = {f"{schema}.{name}" for schema, name in RELATION.findall(notebook.read_text())}
    assert used, f"{notebook.name} reads no warehouse relation"
    assert used <= PUBLISHABLE, f"{notebook.name} reads private data: {sorted(used - PUBLISHABLE)}"


@pytest.mark.parametrize("relation", sorted(PUBLISHABLE))
def test_publishable_relation_exists_in_dbt(relation: str) -> None:
    schema, name = relation.split(".")
    if schema == "reference":
        assert (DBT_DIR / "seeds" / f"{name}.csv").exists()
    else:
        assert (DBT_DIR / "models" / schema / f"{name}.sql").exists()


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_queries_with_execute(notebook: Path) -> None:
    """DuckDB relations (``con.sql``) re-run on every fetch and dropped ``fetchone``;
    notebooks use ``con.execute`` or the showcase helpers instead."""
    assert "con.sql(" not in notebook.read_text()


def test_query_helpers() -> None:
    con = duckdb.connect()
    assert scalar(con, "select 42") == 42
    assert row(con, "select 1, 'a'") == (1, "a")
    assert column(con, "select * from range(3)") == [0, 1, 2]
    with pytest.raises(ValueError, match="one row"):
        row(con, "select * from range(2)")
    with pytest.raises(ValueError, match="one column"):
        scalar(con, "select 1, 2")


def test_lessons_are_never_exported() -> None:
    lines = (REPO_ROOT / "Makefile").read_text().splitlines()
    [line] = [line for line in lines if line.startswith("NOTEBOOKS :=")]
    assert "level2_analysis" in line
    assert "level1_learn" not in line


def test_marimo_cache_is_ignored() -> None:
    """marimo stores cell outputs in __marimo__/; a lesson's outputs hold private data."""
    assert "__marimo__/" in (REPO_ROOT / ".gitignore").read_text().splitlines()


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda p: p.name)
def test_lesson_queries_with_execute(lesson: Path) -> None:
    assert "con.sql(" not in lesson.read_text()
