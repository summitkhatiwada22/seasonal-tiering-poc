"""Manifests: a checksum for every raw file we rely on.

A manifest is a small CSV (one per dataset) that lets a stranger confirm they hold exactly
the same bytes we used. Columns: dataset, url, sha256, bytes, downloaded_utc.
"""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FIELDS = ["dataset", "url", "sha256", "bytes", "downloaded_utc"]


@dataclass(frozen=True)
class ManifestEntry:
    dataset: str
    url: str
    sha256: str
    bytes: int
    downloaded_utc: str


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes, read in chunks so large files stay cheap on memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> list[ManifestEntry]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            ManifestEntry(r["dataset"], r["url"], r["sha256"], int(r["bytes"]), r["downloaded_utc"])
            for r in csv.DictReader(handle)
        ]


def record(
    manifest_path: Path,
    dataset: str,
    url: str,
    file_path: Path,
    *,
    now: datetime | None = None,
) -> ManifestEntry:
    """Add (or replace) the entry for ``url`` using the file's current checksum."""
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = ManifestEntry(dataset, url, sha256_file(file_path), file_path.stat().st_size, stamp)
    kept = [e for e in read_manifest(manifest_path) if (e.dataset, e.url) != (dataset, url)]
    rows = sorted([*kept, entry], key=lambda e: (e.dataset, e.url))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        for e in rows:
            writer.writerow([e.dataset, e.url, e.sha256, e.bytes, e.downloaded_utc])
    os.replace(tmp, manifest_path)
    return entry
