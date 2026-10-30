"""Command line: ``python -m sat.sim`` runs the simulator end to end on synthetic data (D7).

This is a smoke test of the machinery, not a result: the plans are the two trivial extremes
(everything hot, everything in the coldest class) and the providers' own automatic tiering.
Real baselines and the seasonal policies arrive in Phases 4 and 5.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from sat.prices import load_all
from sat.sim import (
    Inventory,
    ITConfig,
    Plan,
    SimResult,
    simulate,
    simulate_autoclass,
    simulate_intelligent_tiering,
)
from sat.synth.generator import SynthConfig, generate


def dense_reads(reads: pl.DataFrame, n_objects: int, start: date, n_days: int) -> np.ndarray:
    """Sparse (object_id, date, reads) rows -> dense array (objects x days)."""
    out = np.zeros((n_objects, n_days), dtype=np.int32)
    obj = reads["object_id"].to_numpy().astype(np.int64)
    offsets = reads.select((pl.col("date") - pl.lit(start)).dt.total_days()).to_series()
    day = offsets.to_numpy().astype(np.int64)
    np.add.at(out, (obj, day), reads["reads"].to_numpy())
    return out


def _row(cloud: str, plan: str, r: SimResult, seconds: float) -> str:
    w = r.waits
    return (
        f"| {cloud} | {plan} | {r.total:,.2f} | {100 * w.share_waited():.2f}% | "
        f"{w.hours_all_reads:,.0f} | {seconds:.1f} |"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sat.sim", description=__doc__)
    parser.add_argument("--objects", type=int, default=10_000)
    parser.add_argument("--days", type=int, default=3 * 365)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prices", type=Path, default=Path("configs/prices"))
    args = parser.parse_args(argv)

    start = date(2021, 1, 1)
    data = generate(
        SynthConfig(n_objects=args.objects, n_days=args.days, seed=args.seed, start=start)
    )
    sizes = data.objects["size_bytes"].to_numpy().astype(np.int64)
    created = data.objects["created_day"].to_numpy().astype(np.int64)
    reads = dense_reads(data.reads, args.objects, start, args.days)
    inv = Inventory(sizes, created_day=created)
    sheets = load_all(args.prices)
    shape = (args.objects, args.days)

    print(f"Synthetic D7: {args.objects:,} objects, {args.days} days from {start}, ", end="")
    print(f"{int(reads.sum()):,} reads, {sizes.sum() / 2**30:,.1f} GiB stored")
    print("Smoke test only: trivial plans, not results.\n")
    print("| Cloud | Plan | Total USD | Reads that waited | Wait hours (all reads) | Seconds |")
    print("| --- | --- | --- | --- | --- | --- |")
    for cloud, sheet in sheets.items():
        for label, index in (("all hot", 0), ("all coldest", len(sheet.tier_order) - 1)):
            t0 = time.perf_counter()
            r = simulate(sheet, inv, reads, Plan(tier=np.full(shape, index, dtype=np.int8)), start)
            print(_row(cloud, f"{label} ({sheet.tier_order[index]})", r, time.perf_counter() - t0))
        if cloud == "aws":
            for label, cfg in (
                ("Intelligent-Tiering", ITConfig()),
                ("Intelligent-Tiering + archive tiers", ITConfig(90, 180)),
            ):
                t0 = time.perf_counter()
                r = simulate_intelligent_tiering(sheet, inv, reads, start, cfg)
                print(_row(cloud, label, r, time.perf_counter() - t0))
        if cloud == "gcs":
            for terminal in ("nearline", "archive"):
                t0 = time.perf_counter()
                r = simulate_autoclass(sheet, inv, reads, start, terminal=terminal)
                print(_row(cloud, f"Autoclass ({terminal} terminal)", r, time.perf_counter() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
