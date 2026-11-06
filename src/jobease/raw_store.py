"""Content-addressed store for raw source files and API responses.

Every input is kept byte-for-byte, named by its SHA-256, so any number in the warehouse
can be traced to the exact file or response it came from. Storing the same bytes twice
is a no-op.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class RawArtifact:
    source: str
    path: Path
    sha256: str
    size_bytes: int
    origin: str
    stored_at: datetime


class RawStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put_bytes(self, source: str, data: bytes, *, suffix: str, origin: str) -> RawArtifact:
        if not source or "/" in source or source.startswith("."):
            raise ValueError(f"invalid source name {source!r}")
        digest = hashlib.sha256(data).hexdigest()
        target = self._root / source / digest[:2] / f"{digest}{suffix}"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            partial.write_bytes(data)
            partial.replace(target)
        return RawArtifact(
            source=source,
            path=target,
            sha256=digest,
            size_bytes=len(data),
            origin=origin,
            stored_at=datetime.now(UTC),
        )

    def put_file(self, source: str, file: Path, *, origin: str | None = None) -> RawArtifact:
        return self.put_bytes(
            source,
            file.read_bytes(),
            suffix="".join(file.suffixes) or ".bin",
            origin=origin or f"file:{file.name}",
        )
