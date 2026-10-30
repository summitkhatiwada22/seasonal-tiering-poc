"""Gate G2, part 3: properties that must hold for any input (random plans and reads)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from sat.prices import PriceSheet, load_all
from sat.sim import (
    Inventory,
    ITConfig,
    Plan,
    Restore,
    SimConfig,
    simulate,
    simulate_autoclass,
    simulate_intelligent_tiering,
)

PRICES = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")
START = date(2019, 3, 1)  # training-period dates only; any calendar works


def _random_case(sheet: PriceSheet, seed: int, n: int = 40, days: int = 200):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    sizes = rng.integers(1_000, 50 * 2**20, n)
    reads = rng.poisson(0.05, (n, days)).astype(np.int32)
    tiers = np.zeros((n, days), dtype=np.int8)
    for i in range(n):  # a few random moves per object
        cuts = np.sort(rng.choice(np.arange(1, days), size=3, replace=False))
        values = rng.integers(0, len(sheet.tier_order), 4)
        for j, (a, b) in enumerate(zip([0, *cuts], [*cuts, days], strict=True)):
            tiers[i, a:b] = values[j]
    clock = rng.integers(0, 400, n)
    created = np.where(rng.random(n) < 0.3, rng.integers(1, days // 2, n), 0)
    reads[np.arange(days)[None, :] < created[:, None]] = 0
    inv = Inventory(sizes, created_day=created)
    return inv, reads, Plan(tier=tiers, initial_clock_days=clock)


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_totals_are_consistent_and_never_negative(cloud: str, seed: int) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _random_case(sheet, seed)
    r = simulate(sheet, inv, reads, plan, START)
    assert all(v >= 0 for v in r.costs.values())
    assert r.total == pytest.approx(r.per_object.sum(), rel=1e-12)
    for cat, series in r.daily.items():
        assert series.sum() == pytest.approx(r.costs[cat], rel=1e-12, abs=1e-15)
        assert (series >= 0).all()
    assert r.waits.reads == reads.sum()
    assert r.waits.cold_reads <= r.waits.reads


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
@pytest.mark.parametrize("seed", [4, 5])
def test_more_reads_never_cost_less(cloud: str, seed: int) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _random_case(sheet, seed)
    extra = np.random.default_rng(seed + 100).poisson(0.05, reads.shape).astype(np.int32)
    extra[np.arange(reads.shape[1])[None, :] < inv.created()[:, None]] = 0
    base = simulate(sheet, inv, reads, plan, START)
    more = simulate(sheet, inv, reads + extra, plan, START)
    assert more.total >= base.total - 1e-12
    assert more.waits.cold_reads >= base.waits.cold_reads


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
def test_count_weighting_equals_repeating_rows(cloud: str) -> None:
    sheet = PRICES[cloud]
    inv, reads, plan = _random_case(sheet, 7, n=5)
    counts = np.array([3, 1, 2, 1, 5])
    weighted = simulate(
        sheet, Inventory(inv.sizes(), count=counts, created_day=inv.created()), reads, plan, START
    )
    rep = np.repeat(np.arange(5), counts)
    clock = np.asarray(plan.initial_clock_days)[rep]
    repeated = simulate(
        sheet,
        Inventory(inv.sizes()[rep], created_day=inv.created()[rep]),
        reads[rep],
        Plan(tier=np.asarray(plan.tier)[rep], initial_clock_days=clock),
        START,
    )
    assert weighted.total == pytest.approx(repeated.total, rel=1e-12)
    assert weighted.waits.hours_all_reads == pytest.approx(repeated.waits.hours_all_reads)


@pytest.mark.parametrize("cloud", ["aws", "gcs", "azure"])
def test_all_hot_plan_equals_the_closed_form(cloud: str) -> None:
    sheet = PRICES[cloud]
    hot = sheet.tier_order[0]
    rng = np.random.default_rng(11)
    sizes = rng.integers(1, 10 * 2**30, 30)
    reads = rng.poisson(2.0, (30, 366)).astype(np.int32)
    start = date(2020, 1, 1)  # leap year: 366 days = exactly 12 calendar months
    plan = Plan(tier=np.zeros((30, 366), dtype=np.int8))
    r = simulate(sheet, Inventory(sizes), reads, plan, start)
    monthly = sheet.get(hot, "storage_usd_per_gb_month")
    months = 12 if cloud != "gcs" else 366 * 24 / 730  # Google: hourly price x hours
    read_field = "class_b_per_1000" if cloud == "gcs" else "get_per_1000"
    expected = (sizes / 2**30).sum() * monthly * months + reads.sum() * sheet.get(
        hot, read_field
    ) / 1000
    assert r.total == pytest.approx(expected, rel=1e-10)
    assert r.waits.cold_reads == 0


@pytest.mark.parametrize(
    ("cloud", "tier"), [("aws", "glacier_flexible"), ("aws", "deep_archive"), ("azure", "archive")]
)
def test_prewarming_in_time_removes_every_wait(cloud: str, tier: str) -> None:
    sheet = PRICES[cloud]
    n, days = 20, 120
    rng = np.random.default_rng(3)
    reads = np.zeros((n, days), dtype=np.int32)
    read_day = rng.integers(10, days, n)
    reads[np.arange(n), read_day] = 1
    plan_tier = np.full((n, days), sheet.tier_order.index(tier), dtype=np.int8)
    cold = simulate(sheet, Inventory(np.full(n, 2**30)), reads, Plan(tier=plan_tier), START)
    assert cold.waits.cold_reads == n
    restores = [Restore(obj=i, day=int(read_day[i]) - 3, keep_days=5) for i in range(n)]
    warm = simulate(
        sheet, Inventory(np.full(n, 2**30)), reads, Plan(tier=plan_tier, restores=restores), START
    )
    assert warm.waits.cold_reads == 0


def test_low_restore_time_never_waits_longer_than_high() -> None:
    for cloud in ("aws", "azure"):
        sheet = PRICES[cloud]
        inv, reads, plan = _random_case(sheet, 9)
        hi = simulate(sheet, inv, reads, plan, START, SimConfig("high"))
        lo = simulate(sheet, inv, reads, plan, START, SimConfig("low"))
        assert lo.waits.hours_all_reads <= hi.waits.hours_all_reads + 1e-9
        assert lo.waits.cold_reads <= hi.waits.cold_reads


def test_google_never_waits() -> None:
    sheet = PRICES["gcs"]
    inv, reads, plan = _random_case(sheet, 12)
    assert simulate(sheet, inv, reads, plan, START).waits.cold_reads == 0


def test_same_inputs_give_identical_results() -> None:
    sheet = PRICES["aws"]
    inv, reads, plan = _random_case(sheet, 13)
    a = simulate(sheet, inv, reads, plan, START)
    b = simulate(sheet, inv, reads, plan, START)
    assert a.costs == b.costs
    assert (a.per_object == b.per_object).all()


def test_intelligent_tiering_and_autoclass_read_daily_stay_hot() -> None:
    reads = np.ones((3, 200), dtype=np.int32)
    inv = Inventory(np.full(3, 2**30))
    it = simulate_intelligent_tiering(
        PRICES["aws"], inv, reads, START, ITConfig(archive_access_days=90)
    )
    assert it.waits.cold_reads == 0
    days = [START + timedelta(days=i) for i in range(200)]
    hot = sum(3 * 0.023 / calendar.monthrange(d.year, d.month)[1] for d in days)
    assert it.costs["storage"] == pytest.approx(hot, rel=1e-12)
    ac = simulate_autoclass(PRICES["gcs"], inv, reads, START, terminal="archive")
    assert ac.costs["transition"] == 0.0
    assert ac.costs["storage"] == pytest.approx(3 * 0.020 * 200 * 24 / 730, rel=1e-9)


def test_intelligent_tiering_never_charges_retrieval_or_early_deletion() -> None:
    rng = np.random.default_rng(21)
    reads = rng.poisson(0.01, (50, 400)).astype(np.int32)
    inv = Inventory(rng.integers(1_000, 10 * 2**20, 50))
    cfg = ITConfig(archive_access_days=90, deep_archive_access_days=180)
    r = simulate_intelligent_tiering(PRICES["aws"], inv, reads, START, cfg)
    assert r.costs["retrieval"] == 0.0 and r.costs["early_delete"] == 0.0
    assert r.costs["restore_requests"] == 0.0


# ---------------------------------------------------------------- refusals


def test_restore_of_an_object_that_is_not_archived_is_refused() -> None:
    sheet = PRICES["aws"]
    plan = Plan(tier=np.zeros((1, 10), dtype=np.int8), restores=[Restore(0, 2, 3)])
    with pytest.raises(ValueError, match="not archived"):
        simulate(sheet, Inventory([2**30]), np.zeros((1, 10)), plan, START)


def test_unknown_restore_speed_is_refused() -> None:
    sheet = PRICES["aws"]
    tier = np.full((1, 10), sheet.tier_order.index("deep_archive"), dtype=np.int8)
    plan = Plan(tier=tier, restores=[Restore(0, 2, 3, speed="expedited")])  # not for Deep Archive
    with pytest.raises(ValueError, match="expedited"):
        simulate(sheet, Inventory([2**30]), np.zeros((1, 10)), plan, START)


def test_shape_mismatch_and_bad_inputs_are_refused() -> None:
    sheet = PRICES["aws"]
    with pytest.raises(ValueError, match="shape"):
        simulate(sheet, Inventory([1]), np.zeros((1, 10)), Plan(tier=np.zeros((1, 9))), START)
    with pytest.raises(ValueError, match="tier_order"):
        simulate(sheet, Inventory([1]), np.zeros((1, 3)), Plan(tier=np.full((1, 3), 9)), START)
    with pytest.raises(ValueError, match="negative"):
        simulate(sheet, Inventory([1]), -np.ones((1, 3)), Plan(tier=np.zeros((1, 3))), START)
    with pytest.raises(ValueError, match="positive"):
        Inventory([0]).sizes()
    with pytest.raises(ValueError):
        ITConfig(archive_access_days=30)
    with pytest.raises(ValueError):
        simulate_autoclass(PRICES["aws"], Inventory([1]), np.zeros((1, 3)), START)
