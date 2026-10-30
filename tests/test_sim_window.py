"""Phase 4 additions to the simulator: the measurement window and chunked runs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from sat.prices import PriceSheet, load_all
from sat.sim import (
    Inventory,
    Plan,
    Restore,
    SimConfig,
    SimResult,
    merge_results,
    simulate,
    simulate_autoclass,
    simulate_chunked,
    simulate_intelligent_tiering,
)

PRICES = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")
START = date(2019, 3, 1)


def _case(sheet: PriceSheet, seed: int, n: int = 30, days: int = 150):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    sizes = rng.integers(1_000, 50 * 2**20, n)
    reads = rng.poisson(0.08, (n, days)).astype(np.int64)
    tiers = np.zeros((n, days), dtype=np.int64)
    for i in range(n):
        cuts = np.sort(rng.choice(np.arange(1, days), size=3, replace=False))
        values = rng.integers(0, len(sheet.tier_order), 4)
        for j, (a, b) in enumerate(zip([0, *cuts], [*cuts, days], strict=True)):
            tiers[i, a:b] = values[j]
    created = np.where(rng.random(n) < 0.3, rng.integers(1, days // 2, n), 0)
    reads[np.arange(days)[None, :] < created[:, None]] = 0
    restores = []
    archive = [i for i, t in enumerate(sheet.tier_order) if t in {"glacier_flexible", "archive"}]
    if archive and sheet.cloud != "gcs":
        for i in range(n):
            for d in rng.choice(np.arange(1, days), size=2, replace=False):
                if tiers[i, d] in archive and created[i] <= d and tiers[i, d - 1] == tiers[i, d]:
                    restores.append(Restore(int(i), int(d), int(rng.integers(1, 10))))
    plan = Plan(tier=tiers, restores=restores, initial_clock_days=rng.integers(0, 400, n))
    counts = rng.integers(1, 4, n).astype(np.float64)
    return Inventory(sizes, count=counts, created_day=created), reads, plan


def _same(a: SimResult, b: SimResult) -> None:
    for cat in a.costs:
        assert a.costs[cat] == pytest.approx(b.costs[cat], rel=1e-12, abs=1e-12)
        np.testing.assert_allclose(a.daily[cat], b.daily[cat], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(a.per_object, b.per_object, rtol=1e-12, atol=1e-12)
    for field in ("reads", "cold_reads", "cold_object_days", "hours_all_reads", "max_hours"):
        assert getattr(a.waits, field) == pytest.approx(getattr(b.waits, field), rel=1e-12)
    assert a.waits.histogram.keys() == b.waits.histogram.keys()
    for k, v in a.waits.histogram.items():
        assert v == pytest.approx(b.waits.histogram[k], rel=1e-12)


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
@pytest.mark.parametrize("chunk", [1, 7, 30])
def test_chunked_run_equals_one_run(cloud: str, chunk: int) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _case(sheet, 11)
    whole = simulate(sheet, inv, reads, plan, START)
    _same(simulate_chunked(sheet, inv, reads, plan, START, chunk_objects=chunk), whole)


def test_merging_managed_runs_equals_one_run() -> None:
    sheet = PRICES["aws"]
    inv, reads, _ = _case(sheet, 12)
    idle = np.arange(len(inv.sizes())) * 7
    whole = simulate_intelligent_tiering(sheet, inv, reads, START, initial_idle_days=idle)
    parts = [
        simulate_intelligent_tiering(
            sheet,
            Inventory(inv.sizes()[a:b], inv.counts()[a:b], inv.created()[a:b]),
            reads[a:b],
            START,
            initial_idle_days=idle[a:b],
        )
        for a, b in [(0, 10), (10, 11), (11, 30)]
    ]
    _same(merge_results(parts), whole)


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
def test_measurement_window_counts_only_later_reads(cloud: str) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _case(sheet, 13)
    weight = inv.counts()
    base = simulate(sheet, inv, reads, plan, START)
    _same(simulate(sheet, inv, reads, plan, START, SimConfig(measure_from=0)), base)
    previous = base.waits.cold_reads
    for start_day in (1, 40, 90, reads.shape[1]):
        r = simulate(sheet, inv, reads, plan, START, SimConfig(measure_from=start_day))
        assert r.costs == base.costs  # the window changes what is counted, never the bill
        assert r.waits.reads == pytest.approx((reads[:, start_day:].sum(axis=1) * weight).sum())
        assert r.waits.cold_reads <= previous + 1e-9
        previous = r.waits.cold_reads
    assert previous == 0.0


def test_measurement_window_hand_case() -> None:
    """One Deep Archive object read on day 1 and on day 5: each read waits 12 hours (on-demand
    restore). Measuring from day 3 counts only the day-5 read."""
    sheet = PRICES["aws"]
    deep = sheet.tier_order.index("deep_archive")
    reads = np.zeros((1, 8), dtype=np.int64)
    reads[0, 1] = reads[0, 5] = 1
    plan = Plan(tier=np.full((1, 8), deep))
    inv = Inventory([10 * 2**20])
    full = simulate(sheet, inv, reads, plan, START)
    late = simulate(sheet, inv, reads, plan, START, SimConfig(measure_from=3))
    assert full.waits.cold_reads == 2 and full.waits.hours_all_reads == 24
    assert late.waits.reads == 1 and late.waits.cold_reads == 1
    assert late.waits.hours_all_reads == 12
    assert late.total == full.total


@pytest.mark.parametrize("terminal", ["nearline", "archive"])
def test_managed_measurement_window(terminal: str) -> None:
    inv, reads, _ = _case(PRICES["gcs"], 14)
    base = simulate_autoclass(PRICES["gcs"], inv, reads, START, terminal=terminal)
    late = simulate_autoclass(PRICES["gcs"], inv, reads, START, terminal=terminal, measure_from=50)
    assert late.costs == base.costs
    assert late.waits.reads == pytest.approx((reads[:, 50:].sum(axis=1) * inv.counts()).sum())
    it = simulate_intelligent_tiering(PRICES["aws"], inv, reads, START, measure_from=50)
    assert it.waits.reads == late.waits.reads


def test_window_costs_and_extra_charges() -> None:
    sheet = PRICES["azure"]
    inv, reads, plan = _case(sheet, 15)
    r = simulate(sheet, inv, reads, plan, START)
    assert r.total_from(0) == pytest.approx(r.total)
    tail = r.total_from(100)
    assert tail == pytest.approx(sum(v[100:].sum() for v in r.daily.values()))
    extra = np.zeros((len(inv.sizes()), reads.shape[1]))
    extra[3, 120] = 2.5
    r.add_charge("monitoring", extra)
    assert r.total_from(100) == pytest.approx(tail + 2.5)
    assert r.total == pytest.approx(r.per_object.sum())
    with pytest.raises(ValueError):
        r.add_charge("monitoring", np.zeros(3))


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
def test_measured_per_object_cost_and_cold_reads(cloud: str) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _case(sheet, 16)
    r = simulate(sheet, inv, reads, plan, START, SimConfig(measure_from=60))
    assert r.per_object_measured is not None and r.cold_by_object is not None
    assert r.per_object_measured.sum() == pytest.approx(r.total_from(60), rel=1e-12)
    assert r.cold_by_object.sum() == pytest.approx(r.waits.cold_reads, rel=1e-12)
    assert (r.per_object_measured <= r.per_object + 1e-12).all()
    extra = np.zeros((len(inv.sizes()), reads.shape[1]))
    extra[:, 59] = 1.0  # before the window: total only
    extra[:, 60] = 2.0  # inside the window
    before = r.per_object_measured.copy()
    r.add_charge("monitoring", extra)
    np.testing.assert_allclose(r.per_object_measured, before + 2.0)
    it = simulate_intelligent_tiering(
        PRICES["aws"], inv, reads, START, initial_idle_days=400, measure_from=60
    )
    assert it.cold_by_object is not None and it.per_object_measured is not None
    assert it.cold_by_object.sum() == pytest.approx(it.waits.cold_reads)
    assert it.per_object_measured.sum() == pytest.approx(it.total_from(60))
