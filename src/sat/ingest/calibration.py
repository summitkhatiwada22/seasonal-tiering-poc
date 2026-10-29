"""Object-size calibration from D2 (Wikimedia media files) and D5 (IBM object-store trace).

D1, D3 and D4 count reads but not bytes. The simulator needs object sizes, so we measure
how big real objects are here and let those distributions feed decision D-009 (low, central
and high size settings). Nothing in this module tests seasonality.

    d2  -> download one daily mediacounts file (about 0.9 GB, resumable) and summarise the
           average bytes per transfer of every media file in it
    d5  -> summarise one IBM trace file that you downloaded in a browser after accepting
           the SNIA licence (see docs/data_cards/D5-ibm-object-store-traces.md)
"""

from __future__ import annotations

import argparse
import bz2
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sat.ingest.files import download_resumable
from sat.ingest.http import FetchError, make_user_agent
from sat.ingest.manifest import record

D2_DAY = "2023-07-02"
D2_URL = (
    f"https://dumps.wikimedia.org/other/mediacounts/daily/2023/mediacounts.{D2_DAY}.v00.tsv.bz2"
)
D2_BYTES = 869_127_708  # measured by the probe on 2026-10-29
LOG_MIN, LOG_MAX, LOG_STEP = 0.0, 11.0, 0.02  # 1 byte to 100 GB, 550 bins
EDGES = np.arange(LOG_MIN, LOG_MAX + LOG_STEP, LOG_STEP)
QUANTILES = (0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99)


@dataclass
class SizeHistogram:
    """Counts of objects (and optionally transfers) per log10-size bin."""

    objects: np.ndarray = field(default_factory=lambda: np.zeros(len(EDGES) - 1, dtype=np.int64))
    weight: np.ndarray = field(default_factory=lambda: np.zeros(len(EDGES) - 1, dtype=np.int64))
    n_objects: int = 0
    total_bytes: int = 0
    total_weight: int = 0
    skipped: int = 0

    def add(self, sizes: np.ndarray, weights: np.ndarray) -> None:
        keep = sizes >= 1
        self.skipped += int((~keep).sum())
        sizes, weights = sizes[keep], weights[keep]
        bins = np.clip(
            np.floor((np.log10(sizes) - LOG_MIN) / LOG_STEP).astype(np.int64),
            0,
            len(EDGES) - 2,
        )
        np.add.at(self.objects, bins, 1)
        np.add.at(self.weight, bins, weights.astype(np.int64))
        self.n_objects += len(sizes)
        self.total_bytes += int(sizes.sum())
        self.total_weight += int(weights.sum())

    def quantiles(self, counts: np.ndarray) -> dict[str, float]:
        total = counts.sum()
        if total == 0:
            return {}
        cumulative = np.cumsum(counts) / total
        out = {}
        for q in QUANTILES:
            idx = int(np.searchsorted(cumulative, q))
            out[f"p{int(q * 100):02d}"] = float(
                10 ** (EDGES[min(idx, len(EDGES) - 2)] + LOG_STEP / 2)
            )
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "objects": self.n_objects,
            "skipped_lines": self.skipped,
            "mean_bytes_per_object": self.total_bytes / self.n_objects if self.n_objects else 0.0,
            "size_quantiles_by_object": self.quantiles(self.objects),
            "size_quantiles_by_weight": self.quantiles(self.weight),
            "bin_width_log10": LOG_STEP,
            "note": "quantiles are bin mid-points, accurate to about 2.3%",
        }


def summarise_mediacounts(lines: Iterable[str], batch: int = 1_000_000) -> dict[str, Any]:
    """Average bytes per transfer for every file (column 2 / column 3), weighted by transfers."""
    hist = SizeHistogram()
    sizes: list[float] = []
    weights: list[int] = []
    bad = 0

    def flush() -> None:
        if sizes:
            hist.add(np.array(sizes), np.array(weights))
            sizes.clear()
            weights.clear()

    for line in lines:
        parts = line.split("\t", 3)
        try:
            transfers = int(parts[2])
            total = int(parts[1])
        except (IndexError, ValueError):
            bad += 1
            continue
        if transfers <= 0:
            bad += 1
            continue
        sizes.append(total / transfers)
        weights.append(transfers)
        if len(sizes) >= batch:
            flush()
    flush()
    if hist.n_objects == 0:
        raise FetchError("no usable lines: the column layout is not what the data card expects")
    result = hist.summary()
    result["skipped_lines"] += bad
    result["total_transfers"] = hist.total_weight
    return result


READ_OPS = ("GET",)
WRITE_OPS = ("PUT", "POST")


def summarise_ibm_trace(lines: Iterable[str]) -> dict[str, Any]:
    """Summarise an IBM Cloud Object Storage trace.

    Assumed line layout (from the SNIA catalogue and the HotStorage '20 paper, to be
    confirmed on the first real file): ``timestamp operation object_id [size [start end]]``.
    Anything that does not fit is counted, and a trace where most lines do not fit is an error.
    """
    ops: dict[str, int] = {}
    sizes: dict[str, int] = {}
    reads: dict[str, int] = {}
    total = bad = 0
    for line in lines:
        parts = line.split()
        total += 1
        if len(parts) < 3:
            bad += 1
            continue
        op, obj = parts[1], parts[2]
        ops[op] = ops.get(op, 0) + 1
        if len(parts) >= 4 and parts[3].isdigit():
            sizes[obj] = int(parts[3])
        if any(k in op for k in READ_OPS):
            reads[obj] = reads.get(obj, 0) + 1
    if total == 0 or bad / total > 0.5 or not ops:
        raise FetchError(
            f"{bad} of {total} lines do not match 'timestamp operation object_id [size ...]'; "
            "check the file and the data card"
        )
    hist = SizeHistogram()
    if sizes:
        arr = np.fromiter(sizes.values(), dtype=np.float64, count=len(sizes))
        hist.add(arr, np.ones(len(arr), dtype=np.int64))
    n_reads = sum(reads.values())
    reread = sum(c for c in reads.values() if c >= 2)
    return {
        "lines": total,
        "unparsed_lines": bad,
        "operations": dict(sorted(ops.items(), key=lambda kv: -kv[1])),
        "distinct_objects_seen": len(set(sizes) | set(reads)),
        "distinct_objects_read": len(reads),
        "get_requests": n_reads,
        "share_of_gets_to_objects_read_twice_or_more": reread / n_reads if n_reads else 0.0,
        "object_size": hist.summary(),
    }


def _open_text(path: Path) -> Iterable[str]:
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", choices=["d2", "d5"])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--contact", default=os.environ.get("SAT_CONTACT", ""))
    parser.add_argument("--file", type=Path, default=None, help="d5: the trace you downloaded")
    args = parser.parse_args(argv)
    base = args.data_dir.expanduser()

    if args.source == "d2":
        if not args.contact:
            parser.error("--contact (or SAT_CONTACT) is required for downloads")
        dest = base / "raw" / "D2" / f"mediacounts.{D2_DAY}.v00.tsv.bz2"
        download_resumable(
            D2_URL, dest, make_user_agent(args.contact), expected_bytes=D2_BYTES, progress=print
        )
        record(base / "manifests" / "D2.csv", "D2", D2_URL, dest, base=base)
        with bz2.open(dest, "rt", encoding="utf-8", errors="replace") as handle:
            summary = summarise_mediacounts(handle)
        summary["source_file"] = dest.name
        out = base / "processed" / "D2" / "size_calibration.json"
    else:
        if args.file is None or not args.file.exists():
            parser.error("--file must point to a trace file you downloaded")
        summary = summarise_ibm_trace(_open_text(args.file))
        summary["source_file"] = args.file.name
        dest = args.file
        out = base / "processed" / "D5" / "trace_summary.json"
        if dest.is_relative_to(base):
            record(base / "manifests" / "D5.csv", "D5", f"manual:{dest.name}", dest, base=base)
        else:
            print("note: put the trace under <data-dir>/raw/D5/ so it gets a checksum entry")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps({k: v for k, v in summary.items() if k != "operations"}, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
