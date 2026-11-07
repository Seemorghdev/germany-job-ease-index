"""macOS launchd job that runs the daily listing snapshot.

launchd, unlike cron, runs a missed calendar job when the Mac wakes up, so a laptop that
was asleep at the scheduled time still gets its snapshot that day.

The job starts the virtualenv's Python with ``-m jobease``, not the ``.venv/bin/jobease``
launcher: pip rewrites that launcher on every install, and if it loses its execute bit
launchd fails before Python starts, leaving an empty log and no snapshot (7 Nov 2026).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

LABEL = "dev.seemorgh.jobease.snapshot"


def plist(repo_root: Path, *, hour: int, minute: int) -> bytes:
    log_dir = repo_root / "data" / "logs"
    job = {
        "Label": LABEL,
        "ProgramArguments": [
            str(repo_root / ".venv" / "bin" / "python"),
            "-m",
            "jobease",
            "snapshot-listings",
        ],
        "WorkingDirectory": str(repo_root),
        # Log lines reach the file as they happen, so a hung run is visible.
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log_dir / "snapshot.log"),
        "StandardErrorPath": str(log_dir / "snapshot.log"),
        "ProcessType": "Background",
    }
    return plistlib.dumps(job)
