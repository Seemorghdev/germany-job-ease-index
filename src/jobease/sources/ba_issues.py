"""Download BA district unemployment issues into the input folder.

Each issue is checked before it is kept: it must hold one .xlsx workbook whose reporting
month is the one requested. Issues the loader can't read (old .xls files) go to
``_unsupported/``, which the loader ignores. Every kept file gets a line in MANIFEST.csv.
"""

from __future__ import annotations

import csv
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from jobease.config import BaUnemploymentSettings
from jobease.http import HttpError, PoliteClient
from jobease.sources import ba_unemployment
from jobease.sources.xlsx import WorkbookError

log = logging.getLogger("jobease")

MANIFEST = "MANIFEST.csv"
MANIFEST_FIELDS = ("file", "source_url", "fetched_at", "sha256")
UNSUPPORTED = "_unsupported"

Status = Literal["downloaded", "present", "unsupported", "failed", "not tried"]


@dataclass(frozen=True)
class DownloadSummary:
    vintage: str
    status: Status
    detail: str = ""


def issue_url(template: str, vintage: date) -> str:
    return template.format(yyyymm=f"{vintage:%Y%m}")


def _existing(folder: Path, stem: str) -> Path | None:
    for candidate in (folder / f"{stem}.zip", folder / f"{stem}.xlsx"):
        if candidate.exists() or (folder / UNSUPPORTED / candidate.name).exists():
            return candidate
    return None


def _append_manifest(folder: Path, name: str, url: str, sha256: str) -> None:
    path = folder / MANIFEST
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(
            {
                "file": name,
                "source_url": url,
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "sha256": sha256,
            }
        )


def download_issues(
    cfg: BaUnemploymentSettings, vintages: Sequence[date], client: PoliteClient
) -> list[DownloadSummary]:
    """Download the given issues. Stops at the first refused request, so a throttling
    server isn't hit again; the remaining issues are reported as not tried."""
    cfg.dir.mkdir(parents=True, exist_ok=True)
    summaries: list[DownloadSummary] = []
    for index, vintage in enumerate(vintages):
        label = f"{vintage:%Y-%m}"
        if found := _existing(cfg.dir, label):
            summaries.append(DownloadSummary(label, "present", found.name))
            continue
        url = issue_url(cfg.issue_url, vintage)
        try:
            body = client.get(url).content
        except HttpError as exc:
            summaries.append(DownloadSummary(label, "failed", f"{exc} ({url})"))
            rest = vintages[index + 1 :]
            summaries.extend(DownloadSummary(f"{v:%Y-%m}", "not tried") for v in rest)
            break

        target = cfg.dir / f"{label}.zip"
        part = target.with_suffix(".part")
        part.write_bytes(body)
        try:
            parsed = ba_unemployment.parse_workbook(
                part,
                sheet_name=cfg.sheet,
                label_column=cfg.label_column,
                inner_suffix=cfg.inner_suffix,
            )
        except WorkbookError as exc:
            (cfg.dir / UNSUPPORTED).mkdir(exist_ok=True)
            part.replace(cfg.dir / UNSUPPORTED / target.name)
            summaries.append(DownloadSummary(label, "unsupported", str(exc)))
            continue
        if parsed.vintage != vintage:
            part.unlink()
            summaries.append(
                DownloadSummary(label, "failed", f"file reports {parsed.vintage:%Y-%m} ({url})")
            )
            continue

        part.replace(target)
        _append_manifest(cfg.dir, target.name, url, hashlib.sha256(body).hexdigest())
        months = f"{parsed.months[0]:%Y-%m}..{parsed.months[-1]:%Y-%m}"
        detail = f"{target.name}, {len(body):,} bytes, months {months}"
        summaries.append(DownloadSummary(label, "downloaded", detail))
        log.info("ba_unemployment: downloaded %s", detail)
    return summaries
