from __future__ import annotations

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest

from conftest import write_xlsx, zip_one
from jobease.config import BaUnemploymentSettings, load_settings
from jobease.http import PoliteClient
from jobease.sources import ba_issues

OCT = date(2026, 10, 1)
SEP = date(2026, 9, 1)


@pytest.fixture
def cfg(tmp_path: Path) -> BaUnemploymentSettings:
    return replace(
        load_settings().ba,
        dir=tmp_path / "ba",
        issue_url="https://example.test/{yyyymm}/issue-{yyyymm}.zip",
    )


@pytest.fixture
def october_zip(tmp_path: Path, ba_rows: list[list[object]]) -> bytes:
    inner = write_xlsx(tmp_path / "inner.xlsx", {"Übersicht_Kreise": ba_rows})
    return zip_one(tmp_path / "o.zip", "202610_Arbeitslose.xlsx", inner.read_bytes()).read_bytes()


def _client(handler: httpx.MockTransport) -> PoliteClient:
    return PoliteClient(transport=handler, max_retries=1, sleep=lambda _: None)


def test_issue_url_fills_in_the_month() -> None:
    assert ba_issues.issue_url("x/{yyyymm}/y-{yyyymm}.zip", OCT) == "x/202610/y-202610.zip"


def test_downloads_checks_and_records_an_issue(
    cfg: BaUnemploymentSettings, october_zip: bytes
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=october_zip)

    with _client(httpx.MockTransport(handler)) as client:
        [summary] = ba_issues.download_issues(cfg, [OCT], client)

    assert summary.status == "downloaded"
    assert seen == ["https://example.test/202610/issue-202610.zip"]
    assert (cfg.dir / "2026-10.zip").read_bytes() == october_zip
    with (cfg.dir / "MANIFEST.csv").open(encoding="utf-8") as handle:
        [row] = list(csv.DictReader(handle))
    assert row["file"] == "2026-10.zip"
    assert row["source_url"] == seen[0]


def test_present_issue_is_not_downloaded_again(
    cfg: BaUnemploymentSettings, october_zip: bytes
) -> None:
    cfg.dir.mkdir()
    (cfg.dir / "2026-10.zip").write_bytes(october_zip)

    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with _client(httpx.MockTransport(handler)) as client:
        [summary] = ba_issues.download_issues(cfg, [OCT], client)
    assert summary.status == "present"


def test_wrong_month_is_rejected(cfg: BaUnemploymentSettings, october_zip: bytes) -> None:
    with _client(httpx.MockTransport(lambda _: httpx.Response(200, content=october_zip))) as c:
        [summary] = ba_issues.download_issues(cfg, [SEP], c)
    assert summary.status == "failed"
    assert "reports 2026-10" in summary.detail
    assert not list(cfg.dir.glob("*.zip"))


def test_unreadable_issue_is_set_aside(cfg: BaUnemploymentSettings, tmp_path: Path) -> None:
    xls_only = zip_one(tmp_path / "old.zip", "200812_Arbeitslose.xls", b"old binary format")
    body = xls_only.read_bytes()
    with _client(httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
        [summary] = ba_issues.download_issues(cfg, [date(2008, 12, 1)], client)
    assert summary.status == "unsupported"
    assert (cfg.dir / "_unsupported" / "2008-12.zip").exists()
    assert cfg.files() == []


def test_stops_at_the_first_refused_request(cfg: BaUnemploymentSettings) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with _client(httpx.MockTransport(handler)) as client:
        summaries = ba_issues.download_issues(cfg, [OCT, SEP], client)

    assert [s.status for s in summaries] == ["failed", "not tried"]
    assert "429" in summaries[0].detail
    assert calls == 2  # one try plus one retry, then nothing for September
