"""Phase 2, step 1: measure what each data source really looks like.

Run this on a computer with normal internet access (not the build workspace). It only reads
small pieces: directory listings, file sizes from HTTP headers, and the first couple of
megabytes of a few files so we can see the columns. It never downloads a full dataset.

    python3 scripts/probe_sources.py --contact you@example.com --out ./probe_output

The contact address goes into the User-Agent so the data owners can reach you, which is the
polite convention for Wikimedia. Use any address you are happy to share with them.

Standard library only. Requests are spaced at least one second apart.
"""

from __future__ import annotations

import argparse
import bz2
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WIKI_BASE = "https://dumps.wikimedia.org/other/"
SEATTLE_CSV = "https://cos-data.seattle.gov/api/v3/views/tmmm-ytt6/export.csv?accessType=DOWNLOAD"
NPM_API = "https://api.npmjs.org/downloads/"
SNIA_PAGE = "https://iotta.snia.org/traces/key-value/36305"
SAMPLE_BYTES = 2_000_000
PAUSE_SECONDS = 1.1
TIMEOUT = 60

_last_request = 0.0


def _pause() -> None:
    global _last_request
    wait = PAUSE_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _request(
    url: str, ua: str, method: str = "GET", rng: str | None = None
) -> urllib.request.Request:
    headers = {"User-Agent": ua}
    if rng:
        headers["Range"] = rng
    return urllib.request.Request(url, headers=headers, method=method)  # noqa: S310


def head(url: str, ua: str) -> dict[str, Any]:
    """Status, size and timing from a HEAD request. Never raises."""
    _pause()
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(_request(url, ua, "HEAD"), timeout=TIMEOUT) as r:  # noqa: S310
            return {
                "url": url,
                "status": r.status,
                "bytes": int(r.headers.get("Content-Length", -1)),
                "seconds": round(time.monotonic() - t0, 2),
            }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def get_text(url: str, ua: str, limit: int = 3_000_000) -> tuple[str | None, str | None]:
    _pause()
    try:
        with urllib.request.urlopen(_request(url, ua), timeout=TIMEOUT) as r:  # noqa: S310
            return r.read(limit).decode("utf-8", "replace"), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def list_links(html: str) -> list[str]:
    """Names of files and folders linked from an Apache-style directory page."""
    names = re.findall(r'href="([^"?#/][^"?#]*/?)"', html)
    return [n for n in names if not n.startswith(("http", "..", "/"))]


def sample_bz2(url: str, ua: str, nbytes: int = SAMPLE_BYTES, lines: int = 6) -> dict[str, Any]:
    """Fetch the first bytes of a .bz2 file and show its first lines."""
    _pause()
    t0 = time.monotonic()
    try:
        req = _request(url, ua, rng=f"bytes=0-{nbytes - 1}")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
            raw = r.read(nbytes)
            status = r.status
        text = bz2.BZ2Decompressor().decompress(raw).decode("utf-8", "replace")
        first = text.splitlines()[:lines]
        return {
            "url": url,
            "status": status,
            "fetched_bytes": len(raw),
            "seconds": round(time.monotonic() - t0, 2),
            "first_lines": first,
            "columns_in_first_line": len(first[0].split()) if first else 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def probe_wikipedia(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D1 pageview_complete"}
    base = WIKI_BASE + "pageview_complete/"
    html, err = get_text(base, ua)
    if html is None:
        return out | {"error": err}
    entries = list_links(html)
    out["top_level_entries"] = entries[:15]
    years = sorted(e for e in entries if re.fullmatch(r"\d{4}/", e))
    out["year_folders"] = years
    if "2023/" not in years:
        return out | {"note": "no 2023 folder found"}
    html, err = get_text(base + "2023/", ua)
    months = sorted(e for e in list_links(html or "") if re.fullmatch(r"2023-\d\d/", e))
    out["months_2023"] = months
    if not months:
        return out | {"error": err or "no month folders"}
    html, err = get_text(f"{base}2023/{months[0]}", ua)
    files = sorted(e for e in list_links(html or "") if not e.endswith("/"))
    out["files_in_first_month"] = files[:10]
    out["file_count_first_month"] = len(files)
    heads = [head(f"{base}2023/{months[0]}{f}", ua) for f in files[:3]]
    out["head_checks"] = heads
    daily = [f for f in files if f.endswith(".bz2")]
    if daily:
        out["sample"] = sample_bz2(f"{base}2023/{months[0]}{daily[0]}", ua)
    return out


def probe_mediacounts(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D2 mediacounts"}
    base = WIKI_BASE + "mediacounts/daily/"
    html, err = get_text(base, ua)
    if html is None:
        return out | {"error": err}
    entries = list_links(html)
    out["entry_count"] = len(entries)
    out["first_entries"] = entries[:5]
    out["last_entries"] = entries[-5:]
    files = [e for e in entries if not e.endswith("/")]
    picks = [files[0], files[len(files) // 2], files[-1]] if files else []
    out["head_checks"] = [head(base + f, ua) for f in picks]
    if files:
        out["sample"] = sample_bz2(base + files[-1], ua)
    return out


def probe_npm(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D3 npm downloads"}

    def call(path: str) -> Any:
        text, err = get_text(NPM_API + path, ua)
        if text is None:
            return {"error": err}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "not json", "head": text[:200]}

    out["point_last_week_react"] = call("point/last-week/react")
    short = call("range/2023-01-01:2023-01-10/react")
    out["range_10_days"] = {
        "days": len(short.get("downloads", [])),
        "sample": short.get("downloads", [])[:3],
    }
    long = call("range/2020-01-01:2023-01-01/react")
    days = long.get("downloads", [])
    out["range_3_years_requested"] = {
        "days_returned": len(days),
        "first_day": days[0]["day"] if days else None,
        "last_day": days[-1]["day"] if days else None,
        "error": long.get("error"),
    }
    return out


def probe_seattle(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D4 Seattle checkouts"}
    out["head"] = head(SEATTLE_CSV, ua)
    _pause()
    try:
        with urllib.request.urlopen(_request(SEATTLE_CSV, ua), timeout=TIMEOUT) as r:  # noqa: S310
            chunk = r.read(300_000).decode("utf-8", "replace")
            out["content_length_header"] = r.headers.get("Content-Length")
            out["content_type"] = r.headers.get("Content-Type")
        out["first_lines"] = chunk.splitlines()[:5]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def probe_snia(ua: str) -> dict[str, Any]:
    return {"source": "D5 IBM traces (page only, no download)", "page": head(SNIA_PAGE, ua)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contact", required=True, help="address shown in the User-Agent")
    parser.add_argument("--out", default="probe_output", type=Path)
    args = parser.parse_args()
    ua = f"seasonal-tiering-poc/0.1 (research; contact: {args.contact})"
    args.out.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"run_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    for name, fn in [
        ("D1", probe_wikipedia),
        ("D2", probe_mediacounts),
        ("D3", probe_npm),
        ("D4", probe_seattle),
        ("D5", probe_snia),
    ]:
        print(f"probing {name} ...", flush=True)
        report[name] = fn(ua)
    path = args.out / "probe_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"done. wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
