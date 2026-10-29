"""D3: daily npm download counts for a fixed, pre-registered list of packages.

npm's range endpoint silently keeps only the END of a long request (about 18 months), so we
ask for one calendar year at a time and insist that every day comes back. npm asks crawlers
to stay at or below one request per second; the default here is one request every 1.1 s.

    list   -> choose the packages and save the list (or ``--from-file`` with one name per
              line); the saved list is the pre-registered cohort and is never redrawn.
              Default: the 100 highest-ranked packages in the public npm-high-impact list
              plus a seeded random sample from ranks 101-5000 (decision D-020, revised)
    fetch  -> download daily counts (resumable; same JSONL layout as D1)
    flags  -> mark bursty / thin packages using days up to December 2022 only
    build  -> one Parquet file per year
    status

Caveat (decision D-020): popularity today favours packages that survived, so the list is
biased towards long-lived packages. Packages with little history are flagged, not removed.
The npm search endpoint was tried first and does not rank by popularity for a blank query
(it returned one package), so the list comes from a public ranking file instead.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

from sat.ingest import d1_wikipedia as d1
from sat.ingest.http import FetchError, Http, make_user_agent
from sat.ingest.manifest import record

API = "https://api.npmjs.org/downloads/range"
HIGH_IMPACT_URL = "https://raw.githubusercontent.com/wooorm/npm-high-impact/main/lib/top.js"
HEAD_PACKAGES = 100
TAIL_POOL = 5000  # the sample is drawn from ranks HEAD_PACKAGES+1 .. TAIL_POOL
SEED = 20261029
FETCH_START = date(2016, 1, 1)
FETCH_END = date(2025, 12, 31)
DEFAULT_PACKAGES = 300
MAX_PACKAGES = 5000  # far below npm's "unreasonable volume" line; a hard stop on typos


def range_url(package: str, start: date, end: date) -> str:
    quoted = urllib.parse.quote(package, safe="@/")
    return f"{API}/{start:%Y-%m-%d}:{end:%Y-%m-%d}/{quoted}"


def parse_range(body: Any, start: date, end: date) -> dict[date, int]:
    """Turn an answer into {day: downloads}; days must be contiguous through ``end``."""
    if not isinstance(body, dict) or "downloads" not in body:
        raise FetchError(f"unexpected npm answer: {str(body)[:120]}")
    out: dict[date, int] = {}
    for item in body["downloads"]:
        day = date.fromisoformat(str(item["day"]))
        if not start <= day <= end:
            raise FetchError(f"day {day} outside requested range {start}..{end}")
        if day in out:
            raise FetchError(f"day {day} appears twice")
        count = int(item["downloads"])
        if count < 0:
            raise FetchError(f"negative download count on {day}")
        out[day] = count
    if not out:
        return out
    # Allowed: the package did not exist yet, so the answer starts late. Not allowed: a hole
    # in the middle or a missing end (what silent truncation or a half answer looks like).
    first_seen, last_seen = min(out), max(out)
    if last_seen != end or len(out) != (end - first_seen).days + 1:
        raise FetchError(
            f"npm answer for {start}..{end} has gaps (first {first_seen}, last {last_seen})"
        )
    return out


def fetch_package_downloads(
    http: Http, package: str, start: date, end: date, span_years: int
) -> dict[date, int]:
    merged: dict[date, int] = {}
    for first, last in d1.year_chunks(start, end, span_years):
        if (last - first).days + 1 > 500:
            raise ValueError("npm chunks must be 500 days or shorter")
        body = http.get_json(range_url(package, first, last))
        if body is None:
            continue  # unknown package or no data: counts as zero
        if isinstance(body, dict) and "error" in body and "downloads" not in body:
            continue  # "no stats for this package for this range"
        merged.update(parse_range(body, first, last))
    return merged


def parse_high_impact(text: str) -> list[str]:
    """Package names, in rank order, from the quoted strings of ``export const top = [...]``."""
    body = text.split("[", 1)[-1].rsplit("]", 1)[0]
    names = re.findall(r"^\s*'([^']+)',?\s*$", body, flags=re.MULTILINE)
    if len(names) < 1000:
        raise FetchError(f"expected thousands of package names, found {len(names)}")
    return list(dict.fromkeys(names))  # drop repeats, keep first rank


def choose_packages(
    ranked: list[str], n: int, head: int = HEAD_PACKAGES, seed: int = SEED
) -> list[str]:
    """The first ``head`` ranks, then a seeded random sample from the next ranks up to 5000."""
    if not 1 <= n <= MAX_PACKAGES:
        raise ValueError(f"n must be between 1 and {MAX_PACKAGES}")
    if not 0 <= head <= n:
        raise ValueError("head must be between 0 and n")
    pool = ranked[head:TAIL_POOL]
    if len(pool) < n - head:
        raise FetchError(f"only {len(pool)} packages available beyond the first {head}")
    sample = random.Random(seed).sample(pool, n - head)
    return ranked[:head] + sorted(sample, key=ranked.index)


def write_list(path: Path, names: list[str], source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["package", "source", "rank"])
        for i, name in enumerate(names, 1):
            writer.writerow([name, source, i])


def read_list(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [r["package"] for r in csv.DictReader(handle)]


def _paths(data_dir: Path) -> dict[str, Path]:
    return {
        "list": data_dir / "interim" / "D3" / "packages.csv",
        "views": data_dir / "raw" / "D3" / "downloads.jsonl",
        "flags": data_dir / "interim" / "D3" / "flags.csv",
        "out": data_dir / "processed" / "D3",
        "manifest": data_dir / "manifests" / "D3.csv",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["list", "fetch", "flags", "build", "status"])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--contact", default=os.environ.get("SAT_CONTACT", ""))
    parser.add_argument("--packages", type=int, default=DEFAULT_PACKAGES)
    parser.add_argument("--head", type=int, default=HEAD_PACKAGES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--from-file", type=Path, default=None)
    parser.add_argument("--min-interval", type=float, default=1.1)
    args = parser.parse_args(argv)
    base = args.data_dir.expanduser()
    p = _paths(base)

    if args.command == "status":
        listed = len(read_list(p["list"])) if p["list"].exists() else 0
        print(f"packages listed: {listed}; downloaded: {len(d1.read_done(p['views']))}")
        return 0
    if args.command == "flags":
        flagged = d1.compute_flags(p["views"])
        d1.write_flags(p["flags"], flagged)
        marked = sum(1 for f in flagged if f.flags)
        print(f"wrote {p['flags']}: {len(flagged)} packages, {marked} flagged")
        return 0
    if args.command == "build":
        built = d1.build_parquet(p["views"], p["out"], FETCH_START, FETCH_END, key="package")
        print(f"wrote {p['out']}: {built}")
        return 0

    if not args.contact:
        parser.error("--contact (or SAT_CONTACT) is required for downloads")
    http = Http(make_user_agent(args.contact), min_interval=args.min_interval)
    if args.command == "list":
        if p["list"].exists():
            print(f"{p['list']} already exists and is the pre-registered list; not redrawn")
            return 0
        if args.from_file:
            lines = args.from_file.read_text(encoding="utf-8").splitlines()
            names = [x.strip() for x in lines if x.strip()]
            write_list(p["list"], names, f"file:{args.from_file.name}")
        else:
            raw = http.get_bytes(HIGH_IMPACT_URL)
            if raw is None:
                raise FetchError("the npm-high-impact ranking file was not found")
            source = p["list"].with_name("high_impact_top.js")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(raw)
            record(p["manifest"], "D3", HIGH_IMPACT_URL, source, base=base)
            ranked = parse_high_impact(raw.decode("utf-8"))
            chosen = choose_packages(ranked, args.packages, args.head, args.seed)
            write_list(p["list"], chosen, f"npm-high-impact head={args.head} seed={args.seed}")
        record(p["manifest"], "D3", "derived:package-list", p["list"], base=base)
        print(f"saved {len(read_list(p['list']))} packages -> {p['list']}")
        return 0

    names = read_list(p["list"])
    summary = d1.fetch_all(
        http,
        names,
        p["views"],
        FETCH_START,
        FETCH_END,
        1,
        workers=1,
        fetch_one=fetch_package_downloads,
    )
    record(p["manifest"], "D3", "api:npm-range-daily", p["views"], base=base)
    print(f"fetched {summary.done}, already had {summary.skipped}, failed {len(summary.failed)}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    sys.exit(main())
