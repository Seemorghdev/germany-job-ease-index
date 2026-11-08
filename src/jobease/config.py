"""Settings, loaded from one TOML file. Relative paths resolve against the repository root."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "inputs.toml"
SEEDS_DIR = REPO_ROOT / "dbt" / "seeds"
DBT_DIR = REPO_ROOT / "dbt"

GVISYS_DEFAULT_COLUMNS: dict[str, str] = {
    "record_type": "A",
    "text_code": "B",
    "land": "C",
    "rb": "D",
    "kreis": "E",
    "vb": "F",
    "gem": "G",
    "name": "H",
    "area_km2": "I",
    "population": "J",
}


class ConfigError(ValueError):
    """The configuration file is missing a value or holds an invalid one."""


def resolve(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def parse_period(value: str) -> date:
    """Parse a reporting month: ``"2026-10"`` -> ``date(2026, 10, 1)``."""
    try:
        year_text, month_text = value.split("-")
        return date(int(year_text), int(month_text), 1)
    except ValueError as exc:
        raise ConfigError(f"period must look like YYYY-MM, got {value!r}") from exc


@dataclass(frozen=True)
class BaUnemploymentSettings:
    dir: Path
    inner_suffix: str | None
    sheet: str
    label_column: str
    issue_url: str
    download_interval_s: float
    download_max_retries: int
    download_max_backoff_s: float

    def files(self) -> list[Path]:
        """The workbooks to load: every .zip and .xlsx in ``dir``, in name order."""
        if not self.dir.is_dir():
            raise ConfigError(f"[ba_unemployment] dir {self.dir} does not exist")
        return sorted(
            p for p in self.dir.iterdir() if p.suffix.lower() in {".zip", ".xlsx"} and p.is_file()
        )


@dataclass(frozen=True)
class GvisysSettings:
    file: Path
    edition: str
    sheet: str | None
    columns: dict[str, str]


@dataclass(frozen=True)
class JobsucheSettings:
    enabled: bool
    base_url: str
    api_key: str
    radius_km: int
    window_days: int
    min_interval_s: float
    max_retries: int
    timeout_s: float
    snapshot_page_size: int
    snapshot_max_pages: int
    snapshot_lock_wait_s: float
    snapshot_retry_passes: int
    snapshot_retry_cooldown_s: float


@dataclass(frozen=True)
class BkgSettings:
    file: Path
    edition: str
    inner_suffix: str
    source_crs: str
    land_layer: str
    district_layer: str
    municipality_layer: str
    land_area_gf: tuple[int, ...]
    simplify_m: float


@dataclass(frozen=True)
class Settings:
    warehouse: Path
    raw_dir: Path
    exports_dir: Path
    min_population: int
    ba: BaUnemploymentSettings
    gvisys: GvisysSettings
    jobsuche: JobsucheSettings
    bkg: BkgSettings


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"missing [{name}] section")
    return value


def _require(section: dict[str, Any], key: str, section_name: str) -> Any:
    if key not in section:
        raise ConfigError(f"missing '{key}' in [{section_name}]")
    return section[key]


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or Path(os.environ.get("JOBEASE_CONFIG", DEFAULT_CONFIG))
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    paths = _section(raw, "paths")
    ba = _section(raw, "ba_unemployment")
    gv = _section(raw, "destatis_gvisys")
    cities = _section(raw, "cities")
    js = _section(raw, "jobsuche")
    bkg = _section(raw, "bkg_vg250")

    warehouse = os.environ.get("JOBEASE_DUCKDB") or _require(paths, "warehouse", "paths")
    columns = {**GVISYS_DEFAULT_COLUMNS, **gv.get("columns", {})}

    return Settings(
        warehouse=resolve(warehouse),
        raw_dir=resolve(_require(paths, "raw", "paths")),
        exports_dir=resolve(_require(paths, "exports", "paths")),
        min_population=int(_require(cities, "min_population", "cities")),
        ba=BaUnemploymentSettings(
            dir=resolve(_require(ba, "dir", "ba_unemployment")),
            inner_suffix=ba.get("inner_suffix"),
            sheet=str(_require(ba, "sheet", "ba_unemployment")),
            label_column=str(_require(ba, "label_column", "ba_unemployment")),
            issue_url=str(_require(ba, "issue_url", "ba_unemployment")),
            download_interval_s=float(_require(ba, "download_interval_s", "ba_unemployment")),
            download_max_retries=int(_require(ba, "download_max_retries", "ba_unemployment")),
            download_max_backoff_s=float(_require(ba, "download_max_backoff_s", "ba_unemployment")),
        ),
        gvisys=GvisysSettings(
            file=resolve(_require(gv, "file", "destatis_gvisys")),
            edition=str(_require(gv, "edition", "destatis_gvisys")),
            sheet=gv.get("sheet"),
            columns=columns,
        ),
        jobsuche=JobsucheSettings(
            enabled=_require(js, "enabled", "jobsuche") is True,
            base_url=str(_require(js, "base_url", "jobsuche")),
            api_key=str(_require(js, "api_key", "jobsuche")),
            radius_km=int(_require(js, "radius_km", "jobsuche")),
            window_days=int(_require(js, "window_days", "jobsuche")),
            min_interval_s=float(_require(js, "min_interval_s", "jobsuche")),
            max_retries=int(_require(js, "max_retries", "jobsuche")),
            timeout_s=float(_require(js, "timeout_s", "jobsuche")),
            snapshot_page_size=int(_require(js, "snapshot_page_size", "jobsuche")),
            snapshot_max_pages=int(_require(js, "snapshot_max_pages", "jobsuche")),
            snapshot_lock_wait_s=float(_require(js, "snapshot_lock_wait_s", "jobsuche")),
            snapshot_retry_passes=int(_require(js, "snapshot_retry_passes", "jobsuche")),
            snapshot_retry_cooldown_s=float(_require(js, "snapshot_retry_cooldown_s", "jobsuche")),
        ),
        bkg=BkgSettings(
            file=resolve(_require(bkg, "file", "bkg_vg250")),
            edition=str(_require(bkg, "edition", "bkg_vg250")),
            inner_suffix=str(_require(bkg, "inner_suffix", "bkg_vg250")),
            source_crs=str(_require(bkg, "source_crs", "bkg_vg250")),
            land_layer=str(_require(bkg, "land_layer", "bkg_vg250")),
            district_layer=str(_require(bkg, "district_layer", "bkg_vg250")),
            municipality_layer=str(_require(bkg, "municipality_layer", "bkg_vg250")),
            land_area_gf=tuple(int(v) for v in _require(bkg, "land_area_gf", "bkg_vg250")),
            simplify_m=float(_require(bkg, "simplify_m", "bkg_vg250")),
        ),
    )
