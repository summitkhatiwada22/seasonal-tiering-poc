"""Fine size quantiles of an IBM object-store trace (D5), for the size settings of D-032.

The Phase 2 summary kept seven quantiles. Interpolating between p90 (17 MB) and p99 (776 MB)
overstates the trace's mean by about half, so this computes every percentile, plus p99.5 and
p99.9, from the raw trace. Each object's size is the last size the trace gives for it, the same
rule as ``sat.ingest.calibration.summarise_ibm_trace``; the object count and mean must match the
Phase 2 summary, which this module checks when given it.

Runs where the trace is (the owner's computer), with polars and numpy only:

    python -m sat.data.trace_sizes --trace <raw/D5/IBMObjectStoreTrace004Part0> --out <file.json>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

LEVELS = [i / 100 for i in range(1, 100)] + [0.995, 0.999]


def object_sizes(trace: Path) -> np.ndarray:
    # Read whole lines and split them ourselves: lines have 3 to 6 fields, and how a CSV reader
    # treats ragged lines differs between polars versions.
    lines = pl.read_csv(
        trace,
        has_header=False,
        separator="\x1f",
        new_columns=["line"],
        schema_overrides={"line": pl.String},
        quote_char=None,
    )
    parts = pl.col("line").str.split(" ")
    frame = lines.select(
        parts.list.get(2, null_on_oob=True).alias("obj"),
        parts.list.get(3, null_on_oob=True).alias("size"),
    )
    sized = frame.filter(pl.col("size").str.contains(r"^\d+$")).with_row_index("row")
    last = sized.group_by("obj").agg(pl.col("size").sort_by("row").last())
    return last["size"].cast(pl.Int64).to_numpy()


def summarise(sizes: np.ndarray) -> dict[str, object]:
    positive = np.sort(sizes[sizes >= 1]).astype(np.float64)
    q = np.quantile(positive, LEVELS, method="inverted_cdf")
    return {
        "objects": int(len(positive)),
        "mean_bytes_per_object": float(positive.mean()),
        "min_bytes": float(positive[0]),
        "max_bytes": float(positive[-1]),
        "quantiles": {f"{p:.3f}": float(v) for p, v in zip(LEVELS, q, strict=True)},
        "method": "numpy inverted_cdf over objects; size = last size seen per object",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sat.data.trace_sizes")
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phase2-summary", type=Path, help="check count and mean against it")
    args = parser.parse_args(argv)
    result = summarise(object_sizes(args.trace))
    result["source_file"] = args.trace.name
    if args.phase2_summary:
        old = json.loads(args.phase2_summary.read_text())["object_size"]
        same_count = old["objects"] == result["objects"]
        same_mean = abs(old["mean_bytes_per_object"] - result["mean_bytes_per_object"]) < 1e-3
        result["matches_phase2_summary"] = bool(same_count and same_mean)
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "quantiles"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
