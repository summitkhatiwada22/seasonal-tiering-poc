"""D4: Seattle Public Library checkouts by title (monthly counts per title).

The bulk export has no Content-Length and cannot be resumed, so we use the dataset's
Socrata API instead: one calendar year at a time, in pages of 50,000 rows, each page saved
as its own file. A failed run continues with the next missing page (decision D-010 also
keeps our own copy, because the publisher may revise old values).

    inspect -> print the row count, the column names and a size estimate (downloads one page)
    fetch   -> download every page of every year (resumable)
    build   -> convert each year to one Parquet file and check the row counts
    status  -> how many pages are on disk

The field names below follow Socrata's lower-case convention and the header seen in the
probe. ``inspect`` and a one-page trial (``fetch --years 2016 --max-pages 1``) confirm them
before the full run.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.parse
from collections.abc import Callable
from pathlib import Path

import polars as pl

from sat.ingest.http import FetchError, Http, make_user_agent
from sat.ingest.manifest import record

DATASET_ID = "tmmm-ytt6"
BASE = f"https://data.seattle.gov/resource/{DATASET_ID}"
PAGE_ROWS = 50_000
FIRST_YEAR = 2005
LAST_YEAR = 2026
COLUMNS = [
    "usageclass",
    "checkouttype",
    "materialtype",
    "checkoutyear",
    "checkoutmonth",
    "checkouts",
    "title",
    "isbn",
    "creator",
    "publicationyear",
]
INT_COLUMNS = ["checkoutyear", "checkoutmonth", "checkouts"]


def year_condition(year: int, quoted: bool) -> str:
    return f"checkoutyear='{year}'" if quoted else f"checkoutyear={year}"


def count_url(where: str | None) -> str:
    query = {"$select": "count(*)"}
    if where:
        query["$where"] = where
    return f"{BASE}.json?{urllib.parse.urlencode(query)}"


def page_url(where: str, page: int) -> str:
    query = {
        "$select": ",".join(COLUMNS),
        "$where": where,
        "$order": ":id",
        "$limit": str(PAGE_ROWS),
        "$offset": str(page * PAGE_ROWS),
    }
    return f"{BASE}.csv?{urllib.parse.urlencode(query)}"


def parse_count(body: object) -> int:
    try:
        return int(body[0]["count"])  # type: ignore[index]
    except (TypeError, KeyError, IndexError, ValueError) as error:
        raise FetchError(f"unexpected row-count answer: {body!r}") from error


def get_count(http: Http, where: str | None) -> int:
    return parse_count(http.get_json(count_url(where)))


def detect_year_style(http: Http, probe_year: int = 2016) -> bool:
    """True if checkoutyear is text (needs quotes), False if it is a number."""
    errors = []
    for quoted in (True, False):
        try:
            if get_count(http, year_condition(probe_year, quoted)) > 0:
                return quoted
        except FetchError as error:
            errors.append(str(error))
    raise FetchError(f"could not filter by checkoutyear in either style: {errors}")


def read_rows(raw: bytes) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    if not rows:
        raise FetchError("empty page (no header)")
    return rows[0], rows[1:]


def check_header(header: list[str]) -> None:
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise FetchError(f"columns missing from the answer: {missing}; got {header}")


def year_dir(data_dir: Path, year: int) -> Path:
    return data_dir / "raw" / "D4" / f"year={year}"


def expected_rows(total: int, page: int) -> int:
    return min(PAGE_ROWS, total - page * PAGE_ROWS)


def fetch_year(
    http: Http,
    data_dir: Path,
    year: int,
    quoted: bool,
    manifest: Path | None = None,
    max_pages: int | None = None,
    progress: Callable[[str], None] = print,
) -> tuple[int, int]:
    """Download missing pages for one year. Returns (pages written, total rows on server)."""
    where = year_condition(year, quoted)
    total = get_count(http, where)
    folder = year_dir(data_dir, year)
    if total == 0:
        return 0, 0
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / "_count.json"
    if meta.exists():
        before = json.loads(meta.read_text(encoding="utf-8"))["rows"]
        if before != total:
            raise FetchError(
                f"{year}: the publisher changed the row count ({before} -> {total}). "
                "Keep the old copy (decision D-010); start a new data folder for a refresh."
            )
    else:
        meta.write_text(json.dumps({"year": year, "rows": total}), encoding="utf-8")
    pages = -(-total // PAGE_ROWS)
    written = 0
    for page in range(pages):
        if max_pages is not None and page >= max_pages:
            break
        target = folder / f"part-{page:05d}.csv"
        if target.exists():
            continue
        url = page_url(where, page)
        raw = http.get_bytes(url)
        if raw is None:
            raise FetchError(f"{year} page {page}: server answered 404")
        header, rows = read_rows(raw)
        check_header(header)
        if len(rows) != expected_rows(total, page):
            raise FetchError(
                f"{year} page {page}: got {len(rows)} rows, expected {expected_rows(total, page)}"
            )
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, target)
        if manifest is not None:
            record(manifest, "D4", url, target, base=data_dir)
        written += 1
        progress(f"{year}: page {page + 1} / {pages}")
    return written, total


def build_year(data_dir: Path, year: int) -> dict[str, int]:
    """Parquet for one year; refuses to write if rows on disk differ from the server count."""
    folder = year_dir(data_dir, year)
    expected = json.loads((folder / "_count.json").read_text(encoding="utf-8"))["rows"]
    parts = sorted(folder.glob("part-*.csv"))
    if len(parts) != -(-expected // PAGE_ROWS):
        raise FetchError(
            f"{year}: {len(parts)} pages on disk, expected {-(-expected // PAGE_ROWS)}"
        )
    frames = [pl.read_csv(p, infer_schema_length=0) for p in parts]  # read all as text first
    frame = pl.concat(frames).with_columns([pl.col(c).cast(pl.Int64) for c in INT_COLUMNS])
    if frame.height != expected:
        raise FetchError(f"{year}: {frame.height} rows on disk, server said {expected}")
    out = data_dir / "processed" / "D4" / f"year={year}" / "checkouts.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out, compression="zstd")
    return {"rows": frame.height, "checkouts": int(frame["checkouts"].sum())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["inspect", "fetch", "build", "status"])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument(
        "--contact", default=os.environ.get("SAT_CONTACT", os.environ.get("WIKIMEDIA_CONTACT", ""))
    )
    parser.add_argument(
        "--years", default=f"{FIRST_YEAR}-{LAST_YEAR}", help="e.g. 2016 or 2010-2015"
    )
    parser.add_argument("--max-pages", type=int, default=None, help="trial runs only")
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    data_dir = args.data_dir.expanduser()
    first, _, last = args.years.partition("-")
    years = list(range(int(first), int(last or first) + 1))
    manifest = data_dir / "manifests" / "D4.csv"

    if args.command == "status":
        for y in years:
            n = len(list(year_dir(data_dir, y).glob("part-*.csv")))
            if n:
                print(f"{y}: {n} pages")
        return 0
    if args.command == "build":
        for y in years:
            if (year_dir(data_dir, y) / "_count.json").exists():
                print(y, build_year(data_dir, y))
        return 0

    if not args.contact:
        parser.error("--contact (or WIKIMEDIA_CONTACT) is required for downloads")
    http = Http(make_user_agent(args.contact), min_interval=args.min_interval, timeout=180.0)
    quoted = detect_year_style(http)
    if args.command == "inspect":
        total = get_count(http, None)
        raw = http.get_bytes(page_url(year_condition(years[0], quoted), 0))
        if raw is None:
            raise FetchError("no data returned for the sample page")
        header, rows = read_rows(raw)
        check_header(header)
        per_row = len(raw) / max(len(rows), 1)
        print(f"rows on server: {total:,}; year filter is {'text' if quoted else 'numeric'}")
        print(f"columns: {header}")
        print(f"sample page: {len(rows)} rows, {len(raw) / 1e6:.1f} MB")
        print(f"estimated download: {total * per_row / 1e9:.1f} GB (sample year may differ)")
        return 0

    for y in years:
        written, total = fetch_year(
            http, data_dir, y, quoted, manifest, args.max_pages, progress=print
        )
        print(f"{y}: {total:,} rows on server, {written} new pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
