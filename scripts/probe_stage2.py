"""Phase 2, step 1b: second probe, answering what the first probe could not.

Questions this run answers:
  * How fast is a sustained download from Wikimedia (not just the first 2 MB)?
  * Does Wikimedia offer a monthly file, and how big is it?
  * What do the mediacounts files look like (fields, size, date range)?
  * Can the Wikimedia per-article API give daily views for a chosen list of articles?
  * How fast does the Seattle export stream, and what years does it cover?

Run it in the same folder as probe_sources.py (it reuses that file's helpers):

    python3 probe_stage2.py --contact you@example.com --out probe_output

Reads at most about 80 MB in total. Standard library only. Python 3.9 or newer.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe_sources import (
    SEATTLE_CSV,
    TIMEOUT,
    WIKI_BASE,
    _pause,
    _request,
    get_text,
    head,
    list_links,
    sample_bz2,
)

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/"
THROUGHPUT_BYTES = 30_000_000
SEATTLE_SECONDS = 60


def throughput(url: str, ua: str, nbytes: int = THROUGHPUT_BYTES) -> dict[str, Any]:
    """Download the first nbytes of a file and report MB per second."""
    _pause()
    t0 = time.monotonic()
    got = 0
    try:
        req = _request(url, ua, rng=f"bytes=0-{nbytes - 1}")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
        secs = time.monotonic() - t0
        return {
            "url": url,
            "bytes": got,
            "seconds": round(secs, 1),
            "mb_per_second": round(got / 1e6 / secs, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "bytes": got, "error": f"{type(exc).__name__}: {exc}"}


def descend(base: str, ua: str, max_depth: int = 4) -> dict[str, Any]:
    """Follow the newest folder at each level until files appear."""
    path = base
    trail: list[str] = []
    for _ in range(max_depth):
        html, err = get_text(path, ua)
        if html is None:
            return {"error": err, "trail": trail}
        entries = list_links(html)
        folders = sorted(e for e in entries if e.endswith("/"))
        files = [e for e in entries if not e.endswith("/")]
        if files:
            return {"url": path, "trail": trail, "files": files, "folder_count": len(folders)}
        if not folders:
            return {"url": path, "trail": trail, "files": [], "note": "empty"}
        # Prefer a complete past year (2023) so the result does not depend on today's date.
        pick = "2023/" if "2023/" in folders else folders[-1]
        trail.append(pick)
        path += pick
    return {"url": path, "trail": trail, "note": "max depth reached"}


def probe_monthly(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D1 monthly files"}
    html, err = get_text(WIKI_BASE + "pageview_complete/", ua)
    if html is None:
        return out | {"error": err}
    entries = list_links(html)
    out["non_year_entries"] = [e for e in entries if not re.fullmatch(r"\d{4}/", e)]
    out["first_year_folder"] = sorted(e for e in entries if re.fullmatch(r"\d{4}/", e))[:1]
    if "monthly/" in entries:
        res = descend(WIKI_BASE + "pageview_complete/monthly/", ua)
        out["monthly"] = res
        files = res.get("files", [])
        out["monthly_heads"] = [head(res["url"] + f, ua) for f in files[:4]] if files else []
    return out


def probe_mediacounts(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D2 mediacounts, descended"}
    res = descend(WIKI_BASE + "mediacounts/daily/", ua)
    out["listing"] = {k: v for k, v in res.items() if k != "files"}
    files = res.get("files", [])
    out["file_count"] = len(files)
    out["first_files"] = files[:3]
    if files:
        picks = [files[0], files[len(files) // 2], files[-1]]
        out["head_checks"] = [head(res["url"] + f, ua) for f in picks]
        bz = [f for f in files if f.endswith(".bz2")]
        if bz:
            out["sample"] = sample_bz2(res["url"] + bz[0], ua, lines=8)
    return out


def api_get(path: str, ua: str) -> dict[str, Any]:
    _pause()
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(_request(API + path, ua), timeout=TIMEOUT) as r:  # noqa: S310
            body = json.loads(r.read().decode("utf-8"))
            limits = {
                k: v for k, v in r.headers.items() if "limit" in k.lower() or "retry" in k.lower()
            }
        return {
            "ok": True,
            "seconds": round(time.monotonic() - t0, 2),
            "limit_headers": limits,
            "body": body,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def probe_api(ua: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": "D1 per-article API"}
    for title in ["Albert_Einstein", "Easter", "Christmas_tree"]:
        res = api_get(
            f"per-article/en.wikipedia/all-access/user/{title}/daily/20230101/20231231", ua
        )
        items = res.get("body", {}).get("items", []) if res.get("ok") else []
        out[title] = {
            "ok": res.get("ok"),
            "days_returned": len(items),
            "seconds": res.get("seconds"),
            "limit_headers": res.get("limit_headers"),
            "first": items[:2],
            "error": res.get("error"),
        }
    top = api_get("top/en.wikipedia/all-access/2022/12/all-days", ua)
    arts = top.get("body", {}).get("items", [{}])[0].get("articles", []) if top.get("ok") else []
    out["top_2022_12"] = {
        "ok": top.get("ok"),
        "articles_returned": len(arts),
        "first_three": arts[:3],
        "error": top.get("error"),
    }
    return out


def probe_seattle(ua: str) -> dict[str, Any]:
    """Stream the export for a fixed time and report speed, rows and years seen."""
    out: dict[str, Any] = {"source": "D4 Seattle export, timed stream"}
    _pause()
    t0 = time.monotonic()
    rows = 0
    years: dict[str, int] = {}
    try:
        with urllib.request.urlopen(_request(SEATTLE_CSV, ua), timeout=TIMEOUT) as r:  # noqa: S310
            text = io.TextIOWrapper(r, encoding="utf-8", errors="replace", newline="")
            reader = csv.reader(text)
            header = next(reader)
            out["header"] = header
            year_idx = header.index("CheckoutYear")
            for row in reader:
                rows += 1
                if len(row) > year_idx:
                    years[row[year_idx]] = years.get(row[year_idx], 0) + 1
                if time.monotonic() - t0 > SEATTLE_SECONDS:
                    break
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    secs = time.monotonic() - t0
    out |= {"seconds": round(secs, 1), "rows_read": rows, "rows_per_second": round(rows / secs)}
    out["years_seen"] = dict(sorted(years.items()))
    out["note"] = "Stopped after the time limit; row order in the export is arbitrary."
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contact", required=True)
    parser.add_argument("--out", default="probe_output", type=Path)
    args = parser.parse_args()
    ua = f"seasonal-tiering-poc/0.1 (research; contact: {args.contact})"
    args.out.mkdir(parents=True, exist_ok=True)

    user_file = WIKI_BASE + "pageview_complete/2023/2023-01/pageviews-20230101-user.bz2"
    now = datetime.now(timezone.utc)  # noqa: UP017  (UTC alias needs Python 3.11)
    report: dict[str, Any] = {"run_utc": now.isoformat(timespec="seconds")}
    steps = [
        ("throughput_user_file", lambda: throughput(user_file, ua)),
        ("D1_monthly", lambda: probe_monthly(ua)),
        ("D1_api", lambda: probe_api(ua)),
        ("D2", lambda: probe_mediacounts(ua)),
        ("D4_timed_stream", lambda: probe_seattle(ua)),
    ]
    for name, fn in steps:
        print(f"probing {name} ...", flush=True)
        try:
            report[name] = fn()
        except Exception as exc:  # noqa: BLE001
            report[name] = {"error": f"{type(exc).__name__}: {exc}"}
    path = args.out / "probe_stage2_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"done. wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
