"""Resumable download of one large file (used for the small calibration downloads).

The file is written to ``<name>.part`` and renamed only when complete, so a half-finished
download is never mistaken for a finished one. Re-running continues from where it stopped
using an HTTP Range request. If the server ignores Range we start over rather than glue
mismatched bytes together.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sat.ingest.http import FetchError, Opener, default_opener

CHUNK = 1 << 20


def download_resumable(
    url: str,
    dest: Path,
    user_agent: str,
    *,
    expected_bytes: int | None = None,
    retries: int = 8,
    timeout: float = 60.0,
    opener: Opener | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Download ``url`` to ``dest`` (skipped if it is already complete)."""
    if dest.exists() and (expected_bytes is None or dest.stat().st_size == expected_bytes):
        return dest
    open_url = opener or default_opener
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    problem = "no attempt made"
    for attempt in range(retries + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": user_agent}
        if have:
            headers["Range"] = f"bytes={have}-"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310
        try:
            with open_url(request, timeout) as response:
                status = getattr(response, "status", 200)
                if have and status != 206:
                    have = 0  # server ignored Range: start again from zero
                total = _total_size(response, have, status)
                mode = "ab" if have else "wb"
                with part.open(mode) as sink:
                    written = have
                    while chunk := response.read(CHUNK):
                        sink.write(chunk)
                        written += len(chunk)
                        if progress and total and (written // CHUNK) % 50 == 0:
                            progress(f"{written / 1e6:.0f} / {total / 1e6:.0f} MB")
                final = part.stat().st_size
                want = expected_bytes if expected_bytes is not None else total
                if want is not None and final != want:
                    problem = f"got {final} bytes, expected {want}"
                else:
                    os.replace(part, dest)
                    return dest
        except urllib.error.HTTPError as error:
            whole = expected_bytes is None or (
                part.exists() and part.stat().st_size == expected_bytes
            )
            if error.code == 416 and part.exists() and whole:  # bytes beyond the end: it is whole
                os.replace(part, dest)
                return dest
            if error.code not in {429, 500, 502, 503, 504}:
                raise FetchError(f"HTTP {error.code} for {url}") from error
            problem = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            problem = f"{type(error).__name__}: {error}"
        if attempt < retries:
            sleep(min(2.0**attempt, 60.0))
    raise FetchError(f"gave up on {url} ({problem}); run the same command again to resume")


def _total_size(response: Any, have: int, status: int) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    length = headers.get("Content-Length")
    if length is None:
        return None
    return int(length) + (have if status == 206 else 0)
