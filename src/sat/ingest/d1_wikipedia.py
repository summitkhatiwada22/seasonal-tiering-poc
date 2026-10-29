"""D1: daily Wikipedia page views for a fixed, pre-registered list of articles.

Why not the bulk files? One day of user traffic is 463 MB and a year is about 170 GB; on our
connection (about 0.65 MB/s) that is days of downloading. The per-article API gives the same
numbers for just the articles we care about (decision D-014).

Three steps, each safe to re-run:

    list   -> pick cohort A (most-viewed pages of Jan 2016 to Dec 2022 ONLY) and cohort B
              (random ordinary articles, drawn once and then kept)
    fetch  -> download daily views for each article; resumes where it stopped
    build  -> write one Parquet file per year with a row for every article and every day
    flags  -> mark bursty / thin articles using days up to December 2022 only

The selection rule uses no data after December 2022, so the validation year (2023) and the
sealed test years (2024-2025) cannot influence which articles we study.

A note on zeros: the API leaves out days with no views. We treat a missing day as zero views,
and the quality check in a later step compares totals with an independent source.

    python -m sat.ingest.d1_wikipedia list --data-dir ~/Projects/seasonal-tiering-data
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from sat.ingest.http import FetchError, Http, make_user_agent
from sat.ingest.manifest import record

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
PROJECT = "en.wikipedia"
ACCESS = "all-access"
AGENT = "user"
LIST_FIRST = (2016, 1)
LIST_LAST = (2022, 12)
FETCH_START = date(2016, 1, 1)
FETCH_END = date(2025, 12, 31)
DEFAULT_ARTICLES = 5000
MAX_MISSING_MONTHS = 3  # more gaps than this and the selection is no longer trustworthy
CALIBRATION_ARTICLE = "Albert_Einstein"  # has views every single day

_NAMESPACES = (
    "Special|Wikipedia|Help|Portal|File|Category|Template|Talk|User|Draft|Module|"
    "MediaWiki|Book|TimedText|Media"
)
NAMESPACE_RE = re.compile(rf"^({_NAMESPACES})(_talk)?:", re.IGNORECASE)
EXCLUDED_TITLES = frozenset({"Main_Page", "-"})
# Titles that look like files or web paths ("404.php") are crawler junk, not articles (D-019).
FILE_LIKE_RE = re.compile(
    r"\.(php|html?|aspx?|jsp|cgi|png|jpe?g|gif|svg|ico|txt|xml|css|js|json|pdf)$", re.IGNORECASE
)
RANDOM_URL = (
    "https://en.wikipedia.org/w/api.php?action=query&list=random&rnnamespace=0"
    "&rnfilterredir=nonredirects&rnlimit=500&format=json"
)
BURSTY_SHARE = 0.5  # flag: the 3 busiest months hold more than half of all 2016-2022 views
THIN_NONZERO_DAYS = 365  # flag: fewer than a year's worth of days with any views
SELECTION_CUTOFF = date(2022, 12, 31)


@dataclass(frozen=True)
class Selection:
    """The chosen articles, plus any months for which the server had no top list."""

    rows: list[ArticleRow]
    missing_months: list[tuple[int, int]]


@dataclass(frozen=True)
class ArticleRow:
    article: str
    total_top_views: int
    months_in_top: int
    cohort: str = "A"  # A = most-viewed articles; B = random ordinary articles


def is_article(title: str) -> bool:
    """True for ordinary articles; False for the front page, other namespaces and file-like junk."""
    return (
        title not in EXCLUDED_TITLES
        and NAMESPACE_RE.match(title) is None
        and FILE_LIKE_RE.search(title) is None
    )


def month_range(first: tuple[int, int], last: tuple[int, int]) -> Iterator[tuple[int, int]]:
    year, month = first
    while (year, month) <= last:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


# --- step 1: choose the articles -------------------------------------------------------------


def top_url(year: int, month: int) -> str:
    return f"{API}/top/{PROJECT}/{ACCESS}/{year}/{month:02d}/all-days"


def fetch_top_month(
    http: Http, year: int, month: int, cache_dir: Path
) -> list[tuple[str, int]] | None:
    """The month's most-viewed pages, cached on disk so a re-run costs nothing.

    Returns None if the server has no list for that month (it is missing 2020-07, for one).
    """
    cache = cache_dir / f"{year}-{month:02d}.json"
    if cache.exists():
        body = json.loads(cache.read_text(encoding="utf-8"))
    else:
        body = http.get_json(top_url(year, month))
        if body is None:
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    articles = body["items"][0]["articles"]
    return [(str(a["article"]), int(a["views"])) for a in articles]


def build_article_list(
    http: Http,
    cache_dir: Path,
    n: int = DEFAULT_ARTICLES,
    months: list[tuple[int, int]] | None = None,
    max_missing: int = MAX_MISSING_MONTHS,
) -> Selection:
    """Union of monthly top lists, ordinary articles only, ranked by total views, top n.

    Ties are broken alphabetically so the result is identical on every run. A month the
    server has no list for is skipped and reported; too many gaps is an error.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    chosen = months if months is not None else list(month_range(LIST_FIRST, LIST_LAST))
    if any(m > LIST_LAST for m in chosen):
        raise ValueError("selection may not use months after December 2022")
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    missing: list[tuple[int, int]] = []
    for year, month in chosen:
        top = fetch_top_month(http, year, month, cache_dir)
        if top is None:
            missing.append((year, month))
            continue
        for title, views in top:
            if is_article(title):
                totals[title] = totals.get(title, 0) + views
                counts[title] = counts.get(title, 0) + 1
    if len(missing) > max_missing:
        names = ", ".join(f"{y}-{m:02d}" for y, m in missing)
        raise FetchError(f"too many months without top-pages data ({len(missing)}): {names}")
    ranked = sorted(totals, key=lambda t: (-totals[t], t))[:n]
    return Selection([ArticleRow(t, totals[t], counts[t]) for t in ranked], missing)


def write_article_list(path: Path, rows: list[ArticleRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["article", "total_top_views", "months_in_top", "cohort"])
        for r in rows:
            writer.writerow([r.article, r.total_top_views, r.months_in_top, r.cohort])


def read_article_list(path: Path) -> list[ArticleRow]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            ArticleRow(
                r["article"],
                int(r["total_top_views"]),
                int(r["months_in_top"]),
                r.get("cohort", "A"),
            )
            for r in csv.DictReader(handle)
        ]


def draw_random_articles(http: Http, n: int, exclude: set[str]) -> list[ArticleRow]:
    """Cohort B: ordinary articles drawn at random from the live encyclopedia.

    The draw cannot be seeded, so it is made once, saved, and re-used on every later run
    (the saved list is the pre-registered cohort). Redirects are excluded by the server.
    """
    if n < 0:
        raise ValueError("n must not be negative")
    picked: dict[str, None] = {}
    for _ in range(max(10, 4 * (n // 500 + 1))):
        if len(picked) >= n:
            break
        body = http.get_json(RANDOM_URL)
        if body is None:
            raise FetchError("random-article endpoint not found")
        for item in body["query"]["random"]:
            title = str(item["title"]).replace(" ", "_")
            if is_article(title) and title not in exclude:
                picked[title] = None
    if len(picked) < n:
        raise FetchError(f"could only draw {len(picked)} of {n} random articles")
    return [ArticleRow(t, 0, 0, "B") for t in sorted(picked)[:n]]


@dataclass(frozen=True)
class FlagRow:
    article: str
    views_to_2022: int
    nonzero_days: int
    top3_month_share: float
    flags: str  # "" or a "+"-joined list of: bursty, thin


def compute_flags(jsonl_path: Path, cutoff: date = SELECTION_CUTOFF) -> list[FlagRow]:
    """Describe each article using ONLY days up to ``cutoff`` (never 2023 or later).

    Flags do not remove anything; they let the analysis report results with and without
    suspicious articles (automated traffic, one-off bursts, almost-empty pages).
    """
    rows: list[FlagRow] = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            record_ = json.loads(line)
            by_month: dict[str, int] = {}
            nonzero = 0
            for iso, views in record_["views"].items():
                if date.fromisoformat(iso) > cutoff or views <= 0:
                    continue
                by_month[iso[:7]] = by_month.get(iso[:7], 0) + int(views)
                nonzero += 1
            total = sum(by_month.values())
            top3 = sum(sorted(by_month.values(), reverse=True)[:3])
            share = top3 / total if total else 0.0
            found = []
            if total and share > BURSTY_SHARE:
                found.append("bursty")
            if nonzero < THIN_NONZERO_DAYS:
                found.append("thin")
            rows.append(FlagRow(str(record_["article"]), total, nonzero, share, "+".join(found)))
    return sorted(rows, key=lambda r: r.article)


def write_flags(path: Path, rows: list[FlagRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["article", "views_to_2022", "nonzero_days", "top3_month_share", "flags"])
        for r in rows:
            writer.writerow(
                [r.article, r.views_to_2022, r.nonzero_days, f"{r.top3_month_share:.4f}", r.flags]
            )


# --- step 2: download daily views -------------------------------------------------------------


def article_url(article: str, start: date, end: date) -> str:
    quoted = urllib.parse.quote(article, safe="")
    return (
        f"{API}/per-article/{PROJECT}/{ACCESS}/{AGENT}/{quoted}/daily/{start:%Y%m%d}/{end:%Y%m%d}"
    )


def parse_views(body: Any, start: date, end: date) -> dict[date, int]:
    """Turn an API answer into {day: views}. Anything odd is an error, never a guess."""
    out: dict[date, int] = {}
    for item in body.get("items", []):
        stamp = str(item["timestamp"])
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        if not start <= day <= end:
            raise FetchError(f"day {day} outside requested range {start}..{end}")
        if day in out:
            raise FetchError(f"day {day} appears twice")
        views = int(item["views"])
        if views < 0:
            raise FetchError(f"negative view count on {day}")
        out[day] = views
    return out


def year_chunks(start: date, end: date, span_years: int) -> list[tuple[date, date]]:
    """Split [start, end] at calendar-year boundaries into pieces of span_years years."""
    if span_years < 1 or end < start:
        raise ValueError("span_years must be >= 1 and end must not precede start")
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        stop = min(end, date(cursor.year + span_years - 1, 12, 31))
        chunks.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return chunks


def fetch_article_views(
    http: Http, article: str, start: date, end: date, span_years: int
) -> dict[date, int]:
    merged: dict[date, int] = {}
    for first, last in year_chunks(start, end, span_years):
        body = http.get_json(article_url(article, first, last))
        if body is not None:
            merged.update(parse_views(body, first, last))
    return merged


def detect_span_years(http: Http, start: date, end: date) -> int:
    """Find the longest request the API answers completely.

    Because the API omits zero-view days we cannot spot a cut-off answer on an ordinary
    article. So we test on an article that has views every day: a complete answer has one
    row per day, and anything less means the span is too long.
    """
    total_years = end.year - start.year + 1
    for span in sorted({total_years, 5, 2, 1}, reverse=True):
        if span > total_years:
            continue
        first, last = year_chunks(start, end, span)[0]
        views = parse_views(
            http.get_json(article_url(CALIBRATION_ARTICLE, first, last)) or {}, first, last
        )
        if len(views) == (last - first).days + 1:
            return span
    raise FetchError("the API did not return a complete year for the calibration article")


@dataclass(frozen=True)
class FetchSummary:
    done: int
    failed: list[str]
    skipped: int


def read_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                done.add(str(json.loads(line)["article"]))
            except (json.JSONDecodeError, KeyError):
                continue  # a half-written last line; that article will be fetched again
    return done


def fetch_all(
    http: Http,
    articles: list[str],
    out_path: Path,
    start: date,
    end: date,
    span_years: int,
    workers: int = 4,
    progress: Callable[[str], None] = print,
    fetch_one: Callable[[Http, str, date, date, int], dict[date, int]] = fetch_article_views,
) -> FetchSummary:
    """Download every article not yet in ``out_path``; one JSON line per finished article."""
    meta_path = out_path.with_suffix(".meta.json")
    meta = {"start": start.isoformat(), "end": end.isoformat(), "span_years": span_years}
    previous = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else meta
    if out_path.exists() and previous != meta:
        raise FetchError("existing download used different settings; use a new folder")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    done = read_done(out_path)
    todo = [a for a in articles if a not in done]
    failed: list[str] = []
    finished = 0
    if out_path.exists() and out_path.stat().st_size > 0:
        with out_path.open("rb+") as raw:  # a crash may have left a line without its newline
            raw.seek(-1, os.SEEK_END)
            if raw.read(1) != b"\n":
                raw.write(b"\n")
    with (
        out_path.open("a", encoding="utf-8") as sink,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        futures = {pool.submit(fetch_one, http, a, start, end, span_years): a for a in todo}
        try:
            for future in as_completed(futures):
                article = futures[future]
                try:
                    views = future.result()
                except FetchError as error:
                    failed.append(article)
                    progress(f"failed: {article}: {error}")
                    continue
                line = {"article": article, "views": {d.isoformat(): v for d, v in views.items()}}
                sink.write(json.dumps(line, separators=(",", ":")) + "\n")
                sink.flush()
                finished += 1
                if finished % 100 == 0:
                    progress(f"{finished + len(done)} / {len(articles)} articles done")
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return FetchSummary(done=finished, failed=failed, skipped=len(done))


# --- step 3: write Parquet --------------------------------------------------------------------


def build_parquet(
    jsonl_path: Path, out_dir: Path, start: date, end: date, key: str = "article"
) -> dict[str, Any]:
    """One Parquet per year: columns <key>, date, views. Missing days become 0."""
    days = (end - start).days + 1
    latest: dict[str, dict[str, int]] = {}
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            latest[str(row["article"])] = row["views"]
    names = sorted(latest)
    if not names:
        raise FetchError("no articles to build")
    matrix = np.zeros((len(names), days), dtype=np.int32)
    for i, name in enumerate(names):
        for iso, views in latest[name].items():
            offset = (date.fromisoformat(iso) - start).days
            if not 0 <= offset < days:
                raise FetchError(f"{name}: day {iso} outside {start}..{end}")
            matrix[i, offset] = views
    first_day = np.datetime64(start.isoformat(), "D")
    last_day = np.datetime64(end.isoformat(), "D") + np.timedelta64(1, "D")
    all_days = np.arange(first_day, last_day)
    for year in range(start.year, end.year + 1):
        cols = np.array([i for i, d in enumerate(all_days) if int(str(d)[:4]) == year])
        frame = pl.DataFrame(
            {
                key: np.repeat(np.array(names), len(cols)),
                "date": np.tile(all_days[cols], len(names)),
                "views": matrix[:, cols].ravel(),
            }
        )
        target = out_dir / f"year={year}" / "views.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(target, compression="zstd")
    return {
        "articles": len(names),
        "days": days,
        "share_of_cells_nonzero": float((matrix > 0).mean()),
    }


# --- command line -----------------------------------------------------------------------------


def _paths(data_dir: Path) -> dict[str, Path]:
    return {
        "top_cache": data_dir / "raw" / "D1" / "top",
        "articles": data_dir / "interim" / "D1" / "articles.csv",
        "views": data_dir / "raw" / "D1" / "views.jsonl",
        "flags": data_dir / "interim" / "D1" / "flags.csv",
        "out": data_dir / "processed" / "D1",
        "manifest": data_dir / "manifests" / "D1.csv",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["list", "fetch", "build", "flags", "status"])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--contact", default=os.environ.get("WIKIMEDIA_CONTACT", ""))
    parser.add_argument("--articles", type=int, default=DEFAULT_ARTICLES)
    parser.add_argument("--random-articles", type=int, default=DEFAULT_ARTICLES)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    base = args.data_dir.expanduser()
    p = _paths(base)

    if args.command == "status":
        listed = len(read_article_list(p["articles"])) if p["articles"].exists() else 0
        done = len(read_done(p["views"]))
        print(f"articles listed: {listed}; articles downloaded: {done}")
        return 0
    if args.command == "flags":
        flagged = compute_flags(p["views"])
        write_flags(p["flags"], flagged)
        by_flag = sum(1 for f in flagged if f.flags)
        print(f"wrote {p['flags']}: {len(flagged)} articles, {by_flag} flagged")
        return 0
    if args.command == "build":
        built = build_parquet(p["views"], p["out"], FETCH_START, FETCH_END)
        print(f"wrote {p['out']}: {built}")
        return 0

    if not args.contact:
        parser.error("--contact (or WIKIMEDIA_CONTACT) is required for downloads")
    http = Http(make_user_agent(args.contact), min_interval=args.min_interval)
    if args.command == "list":
        selection = build_article_list(http, p["top_cache"], args.articles)
        rows = list(selection.rows)
        kept_b = (
            [r for r in read_article_list(p["articles"]) if r.cohort == "B"]
            if p["articles"].exists()
            else []
        )
        if kept_b:
            print(f"re-using the {len(kept_b)} random articles already drawn (cohort B)")
            rows += kept_b
        elif args.random_articles > 0:
            rows += draw_random_articles(http, args.random_articles, {r.article for r in rows})
        write_article_list(p["articles"], rows)
        gaps = p["articles"].with_name("missing_months.txt")
        gaps.write_text(
            "".join(f"{y}-{m:02d}\n" for y, m in selection.missing_months), encoding="utf-8"
        )
        if selection.missing_months:
            names = ", ".join(f"{y}-{m:02d}" for y, m in selection.missing_months)
            print(f"note: the server has no top-pages list for: {names} (skipped, recorded)")
        record(p["manifest"], "D1", "derived:article-list", p["articles"], base=base)
        for cached in sorted(p["top_cache"].glob("*.json")):
            ym = cached.stem
            record(p["manifest"], "D1", top_url(int(ym[:4]), int(ym[5:])), cached, base=base)
        cohort_b = sum(1 for r in rows if r.cohort == "B")
        print(f"selected {len(rows)} articles ({cohort_b} random) -> {p['articles']}")
        return 0

    rows = read_article_list(p["articles"])
    span = detect_span_years(http, FETCH_START, FETCH_END)
    print(f"API answers {span}-year requests completely; fetching {len(rows)} articles")
    summary = fetch_all(
        http, [r.article for r in rows], p["views"], FETCH_START, FETCH_END, span, args.workers
    )
    record(p["manifest"], "D1", "api:per-article-daily-views", p["views"], base=base)
    print(f"fetched {summary.done}, already had {summary.skipped}, failed {len(summary.failed)}")
    if summary.failed:
        print("re-run the same command to retry the failed ones")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
