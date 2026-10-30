"""Gate G2, part 1: the simulator against hand calculations.

These expected values were written BEFORE the simulator code, from the official prices and rules in
docs/SIM_RULES.md, as plain arithmetic with literal numbers (not read from the price sheets). The
derivation of each case is in docs/HAND_CALCS.md. The simulator must match every one to a relative
error of 1e-9.
"""

from __future__ import annotations

import math
from datetime import date
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
    SimResult,
    simulate,
    simulate_autoclass,
    simulate_intelligent_tiering,
)

PRICES = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")
AWS, GCS, AZURE = PRICES["aws"], PRICES["gcs"], PRICES["azure"]

GIB = 2**30
KIB_IN_GIB = 1 / 2**20  # 1 KiB expressed in GiB
JAN = date(2023, 1, 1)
GCS_DAY = 24 / 730  # Google: hourly price x 24 = monthly sheet value x 24 / 730


def close(actual: float, expected: float) -> None:
    assert actual == pytest.approx(expected, rel=1e-9, abs=1e-15)


def tiers(sheet: PriceSheet, n_days: int, segments: list[tuple[int, str]]) -> np.ndarray:
    """One object's tier per day: [(first_day, tier_name), ...]."""
    row = np.zeros(n_days, dtype=np.int8)
    for i, (first, name) in enumerate(segments):
        last = segments[i + 1][0] if i + 1 < len(segments) else n_days
        row[first:last] = sheet.tier_order.index(name)
    return row[None, :]


def one(
    sheet: PriceSheet,
    n_days: int,
    segments: list[tuple[int, str]],
    reads_on: dict[int, int] | None = None,
    size: int = GIB,
    restores: tuple[Restore, ...] = (),
    clock: int = 10**6,
    config: SimConfig | None = None,
    start: date = JAN,
) -> SimResult:
    reads = np.zeros((1, n_days), dtype=np.int32)
    for day, count in (reads_on or {}).items():
        reads[0, day] = count
    plan = Plan(tier=tiers(sheet, n_days, segments), restores=restores, initial_clock_days=clock)
    return simulate(sheet, Inventory(np.array([size])), reads, plan, start, config or SimConfig())


# ---------------------------------------------------------------- storage


def test_h01_aws_standard_full_31_day_month_costs_the_monthly_price() -> None:
    r = one(AWS, 31, [(0, "standard")])
    close(r.costs["storage"], 0.023)
    close(r.total, 0.023)


def test_h02_aws_partial_month_is_prorated_by_days_in_that_month() -> None:
    close(one(AWS, 15, [(0, "standard")]).costs["storage"], 0.023 * 15 / 31)
    feb = one(AWS, 28, [(0, "standard")], start=date(2023, 2, 1))
    close(feb.costs["storage"], 0.023)  # 28 of 28 days


def test_h03_aws_deep_archive_three_months_with_40kb_overhead() -> None:
    r = one(AWS, 90, [(0, "deep_archive")])  # 2023-01-01 .. 2023-03-31
    close(r.costs["storage"], 0.00099 * 3)
    close(r.costs["overhead_storage"], 3 * (32 * KIB_IN_GIB * 0.00099 + 8 * KIB_IN_GIB * 0.023))


def test_h09_aws_standard_ia_small_object_billed_at_128kb() -> None:
    r = one(AWS, 31, [(0, "standard_ia")], size=10 * 1024)
    close(r.costs["storage"], 128 * KIB_IN_GIB * 0.0125)


# ---------------------------------------------------------------- moves


def test_h04_aws_lifecycle_standard_to_flexible_for_1000_objects() -> None:
    reads = np.zeros((1, 31), dtype=np.int32)
    plan = Plan(tier=tiers(AWS, 31, [(0, "standard"), (10, "glacier_flexible")]))
    r = simulate(AWS, Inventory(np.array([2**20]), count=np.array([1000])), reads, plan, JAN)
    close(r.costs["transition"], 1000 * 0.03 / 1000)
    gib = 1000 / 1024
    close(r.costs["storage"], gib * 0.023 * 10 / 31 + gib * 0.0036 * 21 / 31)
    close(
        r.costs["overhead_storage"],
        1000 * (32 * KIB_IN_GIB * 0.0036 + 8 * KIB_IN_GIB * 0.023) * 21 / 31,
    )
    close(r.costs["early_delete"], 0.0)


def test_h05_aws_early_deletion_when_flexible_moves_to_deep_archive_after_30_days() -> None:
    r = one(AWS, 31, [(0, "glacier_flexible"), (30, "deep_archive")], clock=0)
    close(r.costs["early_delete"], 60 * 0.0036 * (1 + 32 * KIB_IN_GIB) / 31)
    close(r.costs["transition"], 0.05 / 1000)
    close(r.costs["storage"], 0.0036 * 30 / 31 + 0.00099 * 1 / 31)


def test_h12_gcs_lifecycle_keeps_the_clock_and_a_rewrite_pays_early_deletion() -> None:
    # Google's own example shape: Nearline at creation, lifecycle to Coldline on day 20,
    # rewritten up to Standard on day 80 (80 days after creation, Coldline minimum is 90).
    r = one(GCS, 100, [(0, "nearline"), (20, "coldline"), (80, "standard")], clock=0)
    close(r.costs["transition"], 0.02 / 1000 + 0.005 / 1000)
    close(r.costs["early_delete"], 10 * 0.004 * GCS_DAY)
    close(r.costs["retrieval"], 0.02)
    close(r.costs["storage"], (20 * 0.010 + 60 * 0.004 + 20 * 0.020) * GCS_DAY)


def test_h13_azure_official_rehydration_example_costs_26_dollars() -> None:
    # Microsoft's example: 1,000 GB archived for 90 days, rehydrated to Hot, read once.
    r = one(AZURE, 3, [(0, "archive"), (1, "hot")], reads_on={2: 1}, size=1000 * GIB, clock=89)
    close(r.costs["retrieval"], 20.0)
    close(r.costs["transition"], 5 / 10_000)  # archive read operation
    close(r.costs["early_delete"], (180 - 90) / 30 * 0.002 * 1000)
    close(r.costs["read_requests"], 0.004 / 10_000)
    non_storage = sum(v for k, v in r.costs.items() if "storage" not in k)
    close(non_storage, 26.0005004)
    assert r.waits.cold_reads == 0  # ready at hour 24 + 15 = 39, read at hour 48


def test_h14_azure_cool_early_deletion_after_21_days() -> None:
    r = one(AZURE, 31, [(0, "cool"), (21, "hot")], clock=0)
    close(r.costs["early_delete"], (30 - 21) / 30 * 0.01)
    close(r.costs["transition"], 0.01 / 10_000)  # cool read operation
    close(r.costs["retrieval"], 0.01)


# ---------------------------------------------------------------- reads and restores


def test_h06_aws_flexible_on_demand_read_waits_and_pays_restore() -> None:
    r = one(AWS, 31, [(0, "glacier_flexible")], reads_on={5: 1})
    close(r.costs["restore_requests"], 0.05 / 1000)
    close(r.costs["retrieval"], 0.01)
    # completes hour 125; +24 h = 149 -> next midnight 168; copy lives 43 hours
    close(r.costs["copy_storage"], 0.023 * 43 / (24 * 31))
    close(r.costs["read_requests"], 0.0004 / 1000)
    assert r.waits.cold_reads == 1
    close(r.waits.hours_all_reads, 5.0)
    close(r.waits.hours_first_read, 5.0)

    low = one(AWS, 31, [(0, "glacier_flexible")], reads_on={5: 1}, config=SimConfig("low"))
    close(low.waits.hours_all_reads, 3.0)
    close(low.costs["copy_storage"], 0.023 * 45 / (24 * 31))


def test_h07_aws_prewarm_avoids_the_wait_until_the_copy_expires() -> None:
    r = one(
        AWS,
        31,
        [(0, "glacier_flexible")],
        reads_on={5: 1, 12: 2},
        restores=(Restore(obj=0, day=3, keep_days=7),),
    )
    # pre-warm: completes hour 77, expires at midnight 264 (day 11): 187 copy hours
    # day 12 (hour 288) is after expiry: on-demand restore, completes 293, expires 336: 43 hours
    close(r.costs["restore_requests"], 2 * 0.05 / 1000)
    close(r.costs["retrieval"], 2 * 0.01)
    close(r.costs["copy_storage"], 0.023 * (187 + 43) / (24 * 31))
    close(r.costs["read_requests"], 3 * 0.0004 / 1000)
    assert r.waits.cold_reads == 2
    assert r.waits.cold_object_days == 1
    close(r.waits.hours_all_reads, 10.0)
    close(r.waits.hours_first_read, 5.0)


def test_h08_aws_glacier_instant_reads_pay_get_and_retrieval_each_time() -> None:
    r = one(AWS, 1, [(0, "glacier_instant")], reads_on={0: 10})
    close(r.costs["read_requests"], 10 * 0.01 / 1000)
    close(r.costs["retrieval"], 10 * 0.03)
    assert r.waits.cold_reads == 0


def test_h10_aws_deep_archive_bulk_prewarm_still_pending_waits_the_rest() -> None:
    r = one(
        AWS,
        10,
        [(0, "deep_archive")],
        reads_on={2: 1},
        restores=(Restore(obj=0, day=1, keep_days=3, speed="bulk"),),
    )
    close(r.costs["restore_requests"], 0.025 / 1000)
    close(r.costs["retrieval"], 0.0025)
    close(r.costs["copy_storage"], 0.023 * 72 / (24 * 31))  # 72 -> 144
    assert r.waits.cold_reads == 1
    close(r.waits.hours_all_reads, 24.0)  # ready at hour 72, read at hour 48


def test_h11_gcs_coldline_reads_pay_class_b_and_retrieval() -> None:
    r = one(GCS, 31, [(0, "coldline")], reads_on={10: 3})
    close(r.costs["storage"], 31 * 0.004 * GCS_DAY)
    close(r.costs["read_requests"], 3 * 0.01 / 1000)
    close(r.costs["retrieval"], 3 * 0.02)
    assert r.waits.cold_reads == 0


def test_h15_azure_archive_copy_prewarm() -> None:
    r = one(
        AZURE,
        31,
        [(0, "archive")],
        reads_on={3: 1},
        restores=(Restore(obj=0, day=2, keep_days=2),),
    )
    # completes hour 63, expires midnight 120: 57 hours of Hot copy
    close(r.costs["restore_requests"], 5 / 10_000 + 0.05 / 10_000)  # archive read + hot write
    close(r.costs["retrieval"], 0.02)
    close(r.costs["copy_storage"], 0.0184 * 57 / (24 * 31))
    close(r.costs["read_requests"], 0.004 / 10_000)
    close(r.costs["overhead_storage"], 8 * KIB_IN_GIB * 0.01)
    assert r.waits.cold_reads == 0


def test_h19_aws_copy_is_gone_at_its_expiry_midnight() -> None:
    # pre-warm day 3 keep 7 expires at hour 264 = 00:00 on day 11; a read on day 11 restores again
    r = one(
        AWS,
        31,
        [(0, "glacier_flexible")],
        reads_on={11: 1},
        restores=(Restore(obj=0, day=3, keep_days=7),),
    )
    assert r.waits.cold_reads == 1
    close(r.costs["restore_requests"], 2 * 0.05 / 1000)


def test_h20_aws_asking_again_for_a_restored_copy_is_billed_as_a_get_and_extends_it() -> None:
    # day 3 keep 2: ready 77, expires ceil(125/24)=6 -> hour 144 (67 copy hours)
    # day 5 (hour 120, copy active) keep 5: billed as one GET; new expiry 120 + 120 = 240 (+96 h)
    r = one(
        AWS,
        31,
        [(0, "glacier_flexible")],
        restores=(Restore(obj=0, day=3, keep_days=2), Restore(obj=0, day=5, keep_days=5)),
    )
    close(r.costs["restore_requests"], 0.05 / 1000 + 0.0004 / 1000)
    close(r.costs["retrieval"], 0.01)
    close(r.costs["copy_storage"], 0.023 * (67 + 96) / (24 * 31))


def test_h21_autoclass_nearline_to_standard_is_free() -> None:
    reads = np.zeros((1, 60), dtype=np.int32)
    reads[0, 40] = 1  # idle 40 days: in Nearline
    r = simulate_autoclass(GCS, Inventory(np.array([GIB])), reads, JAN, terminal="archive")
    close(r.costs["transition"], 0.0)
    close(r.costs["storage"], (30 * 0.020 + 11 * 0.010 + 19 * 0.020) * GCS_DAY)


# ---------------------------------------------------------------- managed rivals


def _it(
    n_days: int,
    reads_on: dict[int, int],
    cfg: ITConfig,
    size: int = GIB,
    restore_time: str = "high",
) -> SimResult:
    reads = np.zeros((1, n_days), dtype=np.int32)
    for day, count in reads_on.items():
        reads[0, day] = count
    return simulate_intelligent_tiering(
        AWS, Inventory(np.array([size])), reads, JAN, cfg, restore_time=restore_time
    )


def test_h16_intelligent_tiering_walks_down_and_reads_free_of_retrieval() -> None:
    r = _it(101, {100: 1}, ITConfig())  # 2023-01-01 .. 2023-04-11
    expected_storage = (
        30 * 0.023 / 31  # Frequent, Jan 1-30
        + 0.0125 / 31
        + 0.0125
        + 0.0125  # Infrequent, Jan 31, February, March
        + 11 * 0.004 / 30  # Archive Instant, Apr 1-11
    )
    close(r.costs["storage"], expected_storage)
    close(r.costs["monitoring"], 0.0025 / 1000 * (3 + 11 / 30))
    close(r.costs["read_requests"], 0.0004 / 1000)
    close(r.costs["retrieval"], 0.0)


def test_h18_intelligent_tiering_archive_access_restore_is_free_but_waits() -> None:
    r = _it(100, {95: 1}, ITConfig(archive_access_days=90))
    assert r.waits.cold_reads == 1
    close(r.waits.hours_all_reads, 5.0)
    close(r.costs["restore_requests"], 0.0)
    close(r.costs["retrieval"], 0.0)
    # days 90-95 (Apr 1-6) in Archive Access, then Frequent again from day 96
    close(
        r.costs["overhead_storage"],
        6 / 30 * (32 * KIB_IN_GIB * 0.0036 + 8 * KIB_IN_GIB * 0.023),
    )
    low = _it(100, {95: 1}, ITConfig(archive_access_days=90), restore_time="low")
    close(low.waits.hours_all_reads, 3.0)


def test_intelligent_tiering_small_objects_stay_frequent_without_monitoring() -> None:
    r = _it(100, {}, ITConfig(), size=100 * 1024)
    close(r.costs["monitoring"], 0.0)
    close(r.costs["storage"], 100 * KIB_IN_GIB * 0.023 * (31 / 31 + 28 / 28 + 31 / 31 + 10 / 30))


def test_h17_autoclass_walks_down_and_charges_class_a_to_come_back_from_coldline() -> None:
    reads = np.zeros((1, 101), dtype=np.int32)
    reads[0, 100] = 1
    r = simulate_autoclass(GCS, Inventory(np.array([GIB])), reads, JAN, terminal="archive")
    close(r.costs["storage"], (30 * 0.020 + 60 * 0.010 + 11 * 0.004) * GCS_DAY)
    close(r.costs["read_requests"], 0.0004 / 1000)
    close(r.costs["transition"], 0.005 / 1000)
    close(r.costs["monitoring"], 101 * 0.0025 / 1000 / 30)
    close(r.costs["retrieval"], 0.0)


# ---------------------------------------------------------------- sanity on the arithmetic itself


def test_hand_arithmetic_constants() -> None:
    assert math.isclose(GCS_DAY * 730 / 24, 1.0)
    assert KIB_IN_GIB * 1024 * 1024 == 1.0


# ---------------------------------------------------------------- objects created during the period


def test_h22_aws_object_uploaded_on_day_10_into_standard_ia_then_copied_up() -> None:
    reads = np.zeros((1, 31), dtype=np.int32)
    plan = Plan(tier=tiers(AWS, 31, [(0, "standard_ia"), (20, "standard")]))
    inv = Inventory(np.array([GIB]), created_day=np.array([10]))
    r = simulate(AWS, inv, reads, plan, JAN)
    close(r.costs["write_requests"], 0.01 / 1000)  # PUT into Standard-IA
    close(r.costs["early_delete"], (30 - 10) * 0.0125 / 31)
    close(r.costs["transition"], 0.005 / 1000)  # COPY priced as a Standard PUT
    close(r.costs["retrieval"], 0.01)
    close(r.costs["storage"], 10 * 0.0125 / 31 + 11 * 0.023 / 31)


def test_h23_intelligent_tiering_object_uploaded_on_day_5() -> None:
    reads = np.zeros((1, 40), dtype=np.int32)
    inv = Inventory(np.array([GIB]), created_day=np.array([5]))
    r = simulate_intelligent_tiering(AWS, inv, reads, JAN)
    # Frequent days 5-34 (Jan 6-31: 26 days, Feb 1-4: 4 days), Infrequent days 35-39 (Feb 5-9)
    close(r.costs["storage"], 26 * 0.023 / 31 + 4 * 0.023 / 28 + 5 * 0.0125 / 28)
    close(r.costs["monitoring"], 0.0025 / 1000 * (26 / 31 + 9 / 28))
    close(r.costs["write_requests"], 0.005 / 1000)


def test_reads_before_creation_are_refused() -> None:
    reads = np.zeros((1, 10), dtype=np.int32)
    reads[0, 2] = 1
    plan = Plan(tier=tiers(AWS, 10, [(0, "standard")]))
    with pytest.raises(ValueError, match="before its created_day"):
        simulate(AWS, Inventory(np.array([GIB]), created_day=np.array([5])), reads, plan, JAN)


def test_h24_plan_changes_before_an_object_exists_cost_nothing() -> None:
    # plan says Standard on days 0-4 and Glacier Flexible from day 5; the object is uploaded on
    # day 10, straight into Glacier Flexible: one PUT at that class's price, no transition.
    reads = np.zeros((1, 31), dtype=np.int32)
    plan = Plan(tier=tiers(AWS, 31, [(0, "standard"), (5, "glacier_flexible")]))
    inv = Inventory(np.array([GIB]), created_day=np.array([10]))
    r = simulate(AWS, inv, reads, plan, JAN)
    close(r.costs["transition"], 0.0)
    close(r.costs["write_requests"], 0.03 / 1000)
    close(r.costs["storage"], 21 * 0.0036 / 31)
