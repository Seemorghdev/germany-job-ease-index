from __future__ import annotations

import json
import plistlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import httpx
import pytest

from jobease import cli, launchd, pipeline, warehouse
from jobease.config import Settings, load_settings
from jobease.sources.jobsuche import (
    JobsucheClient,
    JobsucheSchemaError,
    SearchQuery,
    parse_listing,
    parse_page,
)

DAY = date(2026, 11, 9)
TOTAL = 150  # two pages of 100


def _item(reference: str, **extra: object) -> dict[str, object]:
    return {
        "referenznummer": reference,
        "stellenangebotsTitel": "Lagerhelfer (m/w/d) ",
        "firma": "Muster GmbH",
        "hauptberuf": "Lagerhelfer/in",
        "datumErsteVeroeffentlichung": "2026-10-05",
        "aenderungsdatum": "2026-11-02T08:45:32.199",
        "arbeitszeitVollzeit": True,
        "arbeitszeitTeilzeitVormittag": False,
        "arbeitszeitTeilzeitNachmittag": True,
        "istGeringfuegigeBeschaeftigung": False,
        "quereinstiegGeeignet": True,
        "stellenlokationen": [{"adresse": {"plz": "48143", "ort": "Münster", "strasse": "x"}}],
        **extra,
    }


def test_parse_listing_reads_the_v6_fields() -> None:
    listing = parse_listing(_item("10000-1234-S"))
    assert listing.reference == "10000-1234-S"
    assert listing.title == "Lagerhelfer (m/w/d)"
    assert listing.published_on == date(2026, 10, 5)
    assert listing.changed_at == datetime(2026, 11, 2, 8, 45, 32, 199000)
    assert (listing.postcode, listing.place) == ("48143", "Münster")
    assert (listing.full_time, listing.part_time, listing.lateral_entry) == (True, True, True)


def test_parse_listing_tolerates_missing_optional_fields() -> None:
    listing = parse_listing({"referenznummer": "1-S"})
    assert listing.part_time is None
    assert listing.postcode is None


@pytest.mark.parametrize(
    "item",
    [
        {"stellenangebotsTitel": "no reference"},
        _item("1", quereinstiegGeeignet="ja"),
        _item("1", aenderungsdatum="gestern"),
    ],
)
def test_parse_listing_rejects_unexpected_shapes(item: dict[str, object]) -> None:
    with pytest.raises(JobsucheSchemaError):
        parse_listing(item)


def test_empty_page_may_omit_the_list() -> None:
    total, listings, facets = parse_page(json.dumps({"maxErgebnisse": 0}).encode())
    assert (total, listings, facets) == (0, (), {})


def test_snapshot_query_has_no_age_filter() -> None:
    params = SearchQuery("Lagerhelfer", "Münster", 0, None).params(page=2, size=100)
    assert "veroeffentlichtseit" not in params
    assert (params["page"], params["size"]) == (2, 100)


# --- the daily snapshot -------------------------------------------------------------


def _settings(tmp_path: Path, **jobsuche: object) -> Settings:
    # The real config keeps the job board off; these tests switch it on for a mock server.
    base = load_settings()
    options: dict[str, object] = {"min_interval_s": 0, "enabled": True, **jobsuche}
    return replace(
        base,
        warehouse=tmp_path / "w.duckdb",
        raw_dir=tmp_path / "raw",
        jobsuche=replace(base.jobsuche, **options),  # type: ignore[arg-type]
    )


def test_the_shipped_config_keeps_the_job_board_off() -> None:
    assert load_settings().jobsuche.enabled is False


@pytest.mark.parametrize("run", ["snapshot", "counts"])
def test_job_board_calls_refuse_before_any_request(tmp_path: Path, run: str) -> None:
    settings = _settings(tmp_path, enabled=False)
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    def factory() -> JobsucheClient:
        return JobsucheClient(
            base_url="https://example.test/jobs",
            api_key="k",
            transport=httpx.MockTransport(record),
        )

    with pytest.raises(pipeline.JobBoardDisabledError):
        if run == "snapshot":
            pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=factory)
        else:
            pipeline.fetch_counts(settings, client_factory=factory)
    assert requests == []
    assert not settings.warehouse.exists()  # refused before touching the warehouse


def test_cli_reports_the_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["snapshot-listings"]) == 3
    assert "terms of use" in capsys.readouterr().err


def _seed_city(settings: Settings) -> None:
    with warehouse.connect(settings.warehouse) as con:
        con.execute(
            "insert into landing.destatis_municipalities values (?, ?, ?, ?, ?, ?, ?)",
            ["2025", "05515000", "Münster, Stadt", 320_000, 303.3, "abc", datetime.now(UTC)],
        )


def _handler(request: httpx.Request) -> httpx.Response:
    """Page 1: listings 0-99. Page 2: 99-148, so listing 99 slid across the boundary."""
    page = int(request.url.params["page"])
    term = request.url.params["was"]
    numbers = range(100) if page == 1 else range(99, 149)
    body = {
        "maxErgebnisse": TOTAL,
        "ergebnisliste": [_item(f"{term}-{n}") for n in numbers],
        "facetten": {"homeoffice": {"counts": {"prozentual": 2}}},
    }
    return httpx.Response(200, json=body)


def _client() -> JobsucheClient:
    return JobsucheClient(
        base_url="https://example.test/jobs",
        api_key="k",
        transport=httpx.MockTransport(_handler),
        sleep=lambda _: None,
    )


def test_snapshot_pages_through_and_deduplicates(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_city(settings)

    summary = pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=_client)

    terms = summary.terms
    assert (summary.cities, summary.fetched, summary.skipped) == (1, terms, 0)
    assert summary.pages == 2 * terms
    assert summary.listings == 149 * terms  # one duplicate per query dropped
    with duckdb.connect(str(settings.warehouse), read_only=True) as con:
        row = con.execute(
            "select count(*), sum(listings), bool_or(truncated), any_value(facets_json) "
            "from landing.jobsuche_snapshot_queries"
        ).fetchone()
        assert row is not None
        assert row[:3] == (terms, 149 * terms, False)
        assert json.loads(row[3]) == {"homeoffice": {"counts": {"prozentual": 2}}}


def test_snapshot_resumes_the_same_day(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_city(settings)
    pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=_client)

    again = pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=_client)

    assert (again.fetched, again.skipped) == (0, again.terms)


def test_snapshot_marks_queries_cut_off_by_the_page_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, snapshot_max_pages=1)
    _seed_city(settings)

    summary = pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=_client)

    assert summary.truncated == summary.terms
    assert summary.listings == 100 * summary.terms


def _flaky_client(fail_first: int) -> Callable[[], JobsucheClient]:
    """The first ``fail_first`` requests drop the connection, like the BA did on 7 Nov."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fail_first:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return _handler(request)

    def factory() -> JobsucheClient:
        return JobsucheClient(
            base_url="https://example.test/jobs",
            api_key="k",
            max_retries=0,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
        )

    return factory


def test_snapshot_sets_failing_queries_aside_and_retries_them(tmp_path: Path) -> None:
    settings = _settings(tmp_path, snapshot_retry_passes=2, snapshot_retry_cooldown_s=300)
    _seed_city(settings)
    waits: list[float] = []

    summary = pipeline.snapshot_listings(
        settings, snapshot_date=DAY, client_factory=_flaky_client(3), sleep=waits.append
    )

    assert summary.complete
    assert (summary.fetched, summary.failed) == (summary.terms, 0)
    assert waits == [300]  # one cooldown, then the three set-aside queries got through


def test_snapshot_reports_what_is_still_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path, snapshot_retry_passes=1, snapshot_retry_cooldown_s=1)
    _seed_city(settings)

    summary = pipeline.snapshot_listings(
        settings, snapshot_date=DAY, client_factory=_flaky_client(10**6), sleep=lambda _: None
    )

    assert not summary.complete
    assert (summary.fetched, summary.failed) == (0, summary.terms)
    # Nothing half-written: a rerun later that day fetches every query.
    again = pipeline.snapshot_listings(settings, snapshot_date=DAY, client_factory=_client)
    assert (again.fetched, again.skipped, again.failed) == (again.terms, 0, 0)


# --- unattended runs --------------------------------------------------------------------


def test_connect_waits_for_a_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    attempts: list[str] = []
    real_connect = duckdb.connect

    def flaky_connect(path: str) -> duckdb.DuckDBPyConnection:
        attempts.append(path)
        if len(attempts) < 3:
            raise duckdb.IOException('Could not set lock on file "w.duckdb"')
        return real_connect(path)

    monkeypatch.setattr(duckdb, "connect", flaky_connect)
    sleeps: list[float] = []
    with warehouse.connect(tmp_path / "w.duckdb", wait_s=60, sleep=sleeps.append):
        pass
    assert sleeps == [warehouse.LOCK_RETRY_S, warehouse.LOCK_RETRY_S]


def test_connect_gives_up_on_a_lock_without_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def locked(_: str) -> duckdb.DuckDBPyConnection:
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr(duckdb, "connect", locked)
    with pytest.raises(duckdb.IOException), warehouse.connect(tmp_path / "w.duckdb"):
        pass


def test_launchd_plist_runs_the_snapshot_from_the_repo(tmp_path: Path) -> None:
    job = plistlib.loads(launchd.plist(tmp_path / "My Repo", hour=9, minute=0))
    assert job["Label"] == launchd.LABEL
    assert job["ProgramArguments"] == [
        str(tmp_path / "My Repo" / ".venv" / "bin" / "python"),
        "-m",
        "jobease",
        "snapshot-listings",
    ]
    assert job["EnvironmentVariables"] == {"PYTHONUNBUFFERED": "1"}
    assert job["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
    assert job["WorkingDirectory"] == str(tmp_path / "My Repo")
