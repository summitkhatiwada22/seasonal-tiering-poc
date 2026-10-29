"""Phase 2 quality report: one pass/fail check list per dataset.

Run it on the folder that holds the downloaded data. It reads, never changes, the data and
writes ``quality_report.json`` and ``quality_report.md`` into ``--out``. The Phase 2 stop
point is "every dataset passes"; a failed check is a finding to explain, not to hide.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from sat.ingest import d1_wikipedia as d1
from sat.ingest import d3_npm
from sat.ingest.manifest import verify_manifest


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _manifest_check(base: Path, dataset: str) -> Check:
    path = base / "manifests" / f"{dataset}.csv"
    if not path.exists():
        return Check("manifest present", False, f"{path} not found")
    result = verify_manifest(path, base)
    detail = f"{result.checked} files re-checked, {result.unverifiable} without stored path"
    if result.missing or result.changed:
        detail += f"; missing {result.missing[:3]}, changed {result.changed[:3]}"
    return Check("manifest checksums match", result.ok and result.checked > 0, detail)


def check_daily(
    base: Path, dataset: str, key: str, start: date, end: date, list_path: Path, flags_path: Path
) -> list[Check]:
    """Checks for a dense daily table (D1 articles, D3 packages)."""
    files = sorted((base / "processed" / dataset).glob("year=*/views.parquet"))
    if not files:
        return [
            Check("processed data present", False, f"no Parquet files under processed/{dataset}")
        ]
    frame = pl.concat([pl.read_parquet(f) for f in files])
    days = (end - start).days + 1
    first_day: Any = frame.select(pl.col("date").min()).item()
    last_day: Any = frame.select(pl.col("date").max()).item()
    lowest: Any = frame.select(pl.col("views").min()).item()
    keys = frame[key].n_unique()
    listed = _listed_keys(list_path, key)
    out = [
        Check(
            "date range complete",
            first_day == start and last_day == end,
            f"{first_day} .. {last_day}, expected {start} .. {end}",
        ),
        Check(
            "rows = items x days",
            frame.height == keys * days,
            f"{frame.height:,} rows; {keys:,} items x {days:,} days = {keys * days:,}",
        ),
        Check(
            "no duplicate (item, date)",
            frame.select([key, "date"]).unique().height == frame.height,
            "unique pairs equal rows",
        ),
        Check("no negative counts", int(lowest) >= 0, f"min {lowest}"),
        Check(
            "every listed item downloaded",
            listed is not None and set(frame[key].unique()) == listed,
            f"{keys:,} in data, {len(listed) if listed is not None else 'no'} listed",
        ),
    ]
    nonzero = float((frame["views"] > 0).mean() or 0.0)  # type: ignore[arg-type]
    out.append(Check("not mostly empty", nonzero > 0.5, f"{nonzero:.1%} of cells above zero"))
    if flags_path.exists():
        with flags_path.open(encoding="utf-8") as handle:
            flagged = [r["flags"] for r in csv.DictReader(handle)]
        shares = {f: sum(1 for x in flagged if f in x) for f in ("bursty", "thin")}
        out.append(
            Check(
                "flags computed (informational)",
                True,
                f"{len(flagged):,} items; bursty {shares['bursty']:,}, thin {shares['thin']:,}",
            )
        )
    else:
        out.append(Check("flags computed (informational)", False, "run the flags command"))
    out.append(_manifest_check(base, dataset))
    return out


def _listed_keys(path: Path, key: str) -> set[str] | None:
    if not path.exists():
        return None
    column = "article" if key == "article" else "package"
    with path.open(encoding="utf-8", newline="") as handle:
        return {r[column] for r in csv.DictReader(handle)}


def check_d4(base: Path) -> list[Check]:
    folders = sorted((base / "raw" / "D4").glob("year=*"))
    if not folders:
        return [Check("raw data present", False, "no raw/D4/year=* folders")]
    out: list[Check] = []
    total = 0
    bad: list[str] = []
    for folder in folders:
        year = int(folder.name.split("=")[1])
        expected = json.loads((folder / "_count.json").read_text(encoding="utf-8"))["rows"]
        parquet = base / "processed" / "D4" / folder.name / "checkouts.parquet"
        if not parquet.exists():
            bad.append(f"{year}: not built")
            continue
        frame = pl.read_parquet(parquet)
        months = set(frame["checkoutmonth"].unique().to_list())
        if frame.height != expected or not months <= set(range(1, 13)):
            bad.append(
                f"{year}: {frame.height} rows vs {expected} on server, months {sorted(months)}"
            )
        if (frame["checkouts"] < 0).any():
            bad.append(f"{year}: negative checkouts")
        if (frame["checkoutyear"] != year).any():
            bad.append(f"{year}: rows from another year")
        total += frame.height
    out.append(
        Check(
            "every year matches the server row count",
            not bad,
            "; ".join(bad) or f"{total:,} rows in {len(folders)} years",
        )
    )
    out.append(_manifest_check(base, "D4"))
    return out


def check_summary(base: Path, dataset: str, relative: str) -> list[Check]:
    path = base / "processed" / dataset / relative
    if not path.exists():
        return [Check("calibration summary present", False, f"{path} not found")]
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    quantiles = data.get("size_quantiles_by_object") or data.get("object_size", {}).get(
        "size_quantiles_by_object", {}
    )
    ok = bool(quantiles) and quantiles.get("p50", 0) > 0
    return [
        Check(
            "size distribution measured", ok, f"median bytes about {quantiles.get('p50', 'n/a')}"
        ),
        _manifest_check(base, dataset),
    ]


def run(base: Path) -> dict[str, list[Check]]:
    return {
        "D1": check_daily(
            base,
            "D1",
            "article",
            d1.FETCH_START,
            d1.FETCH_END,
            base / "interim" / "D1" / "articles.csv",
            base / "interim" / "D1" / "flags.csv",
        ),
        "D2": check_summary(base, "D2", "size_calibration.json"),
        "D3": check_daily(
            base,
            "D3",
            "package",
            d3_npm.FETCH_START,
            d3_npm.FETCH_END,
            base / "interim" / "D3" / "packages.csv",
            base / "interim" / "D3" / "flags.csv",
        ),
        "D4": check_d4(base),
        "D5": check_summary(base, "D5", "trace_summary.json"),
    }


def to_markdown(results: dict[str, list[Check]]) -> str:
    lines = ["# Phase 2 quality report", ""]
    for name, checks in results.items():
        verdict = "PASS" if all(c.ok for c in checks) else "FAIL"
        lines += [f"## {name}: {verdict}", "", "| Check | Result | Detail |", "| --- | --- | --- |"]
        lines += [f"| {c.name} | {'pass' if c.ok else '**FAIL**'} | {c.detail} |" for c in checks]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", nargs="*", default=None, help="e.g. D1 D4")
    args = parser.parse_args(argv)
    results = run(args.data_dir.expanduser())
    if args.only:
        results = {k: v for k, v in results.items() if k in args.only}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "quality_report.json").write_text(
        json.dumps({k: [asdict(c) for c in v] for k, v in results.items()}, indent=2),
        encoding="utf-8",
    )
    (args.out / "quality_report.md").write_text(to_markdown(results), encoding="utf-8")
    print(to_markdown(results))
    return 0 if all(c.ok for v in results.values() for c in v) else 1


if __name__ == "__main__":
    sys.exit(main())
