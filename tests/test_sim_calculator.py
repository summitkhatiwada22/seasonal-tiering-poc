"""Gate G2, part 2: the simulator reproduces the owner's AWS Pricing Calculator readings.

The calculator scenarios (docs/evidence/aws-calculator-*.png, 2026-10-29/30) price one month. We
simulate a 31-day month (January 2023, so one month = the monthly price) with the same objects and
retrievals, and compare the line items the calculator includes. The simulator also charges items
the calculator form left out (restore requests, the temporary copy, GETs); those are listed but
not part of the comparison.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from sat.prices import load_all
from sat.sim import Inventory, Plan, SimResult, simulate

AWS = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")["aws"]
MIB = 2**20
JAN = date(2023, 1, 1)


def _month(tier: str, total_gib: int, retrieved_gib: int, object_mib: int = 16) -> SimResult:
    """``total_gib`` in ``object_mib`` objects; ``retrieved_gib`` of them read once on day 0."""
    per_gib = 1024 // object_mib
    n_read, n_rest = retrieved_gib * per_gib, (total_gib - retrieved_gib) * per_gib
    rows = [(n, read) for n, read in ((n_read, 1), (n_rest, 0)) if n > 0]
    inv = Inventory(np.full(len(rows), object_mib * MIB), count=np.array([n for n, _ in rows]))
    reads = np.zeros((len(rows), 31), dtype=np.int32)
    reads[:, 0] = [read for _, read in rows]
    plan = Plan(tier=np.full((len(rows), 31), AWS.tier_order.index(tier), dtype=np.int8))
    return simulate(AWS, inv, reads, plan, JAN)


def _calculator_items(r: SimResult) -> float:
    return r.costs["storage"] + r.costs["overhead_storage"] + r.costs["retrieval"]


def test_c1_glacier_flexible_10000_gb_with_1000_gb_retrieved_is_46_18() -> None:
    r = _month("glacier_flexible", 10_000, 1_000)
    assert round(_calculator_items(r), 2) == 46.18
    # Also charged by the simulator (not entered in the calculator form): 64,000 restore requests
    assert round(r.costs["restore_requests"], 2) == round(64_000 * 0.05 / 1000, 2)


def test_c2_deep_archive_100000_gb_with_1000_gb_retrieved_is_120_32() -> None:
    r = _month("deep_archive", 100_000, 1_000)
    assert round(_calculator_items(r), 2) == 120.32


def test_c3_standard_10000_gb_is_230_plus_the_s3_select_line() -> None:
    r = _month("standard", 10_000, 0)
    s3_select_returned = 1_000 * 0.0007  # calculator line for S3 Select; not simulated
    assert round(r.costs["storage"], 2) == 230.00
    assert round(r.costs["storage"] + s3_select_returned, 2) == 230.70


def test_c4_glacier_instant_10000_gb_with_1000_gb_retrieved_is_70_00() -> None:
    r = _month("glacier_instant", 10_000, 1_000)
    assert round(r.costs["storage"] + r.costs["retrieval"], 2) == 70.00
    assert r.waits.cold_reads == 0
