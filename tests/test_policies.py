"""Phase 4 policies: hand cases with known answers, causality, and the AWS rule checks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from sat.policies import (
    Autoclass,
    AzureLastAccess,
    IntelligentTiering,
    ITPrewarm,
    Lifecycle,
    Planner,
    PlanRuleError,
    Scenario,
    TwoTier,
    check_aws_plan,
    policy_grid,
)
from sat.policies.rules import check_lifecycle_steps
from sat.policies.scenario import MAX_AHEAD
from sat.prices import load_all
from sat.sim import Inventory, ITConfig, Plan, simulate_intelligent_tiering

PRICES = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")
BIG = 50 * 2**20
HIST = date(2016, 1, 1)


def _scn(
    cloud: str,
    reads: np.ndarray,
    sim_start: int,
    n_days: int,
    sizes: list[int] | None = None,
    created: list[int] | None = None,
    measure_from: int = 0,
) -> Scenario:
    n = reads.shape[0]
    return Scenario(
        "test",
        PRICES[cloud],
        np.array(sizes or [BIG] * n, dtype=np.int64),
        reads.astype(np.int64),
        np.array(created or [0] * n, dtype=np.int64),
        HIST,
        sim_start,
        n_days,
        measure_from,
    )


def _names(scn: Scenario, tier: np.ndarray) -> list[str]:
    return [scn.sheet.tier_order[t] for t in tier]


# ------------------------------------------------------------------ seasonal-naive hand cases


def test_seasonal_warms_ahead_of_last_years_read() -> None:
    """Read once at absolute day 600. Same day last year for window day w is 800 + w - 364, so the
    prediction lands on w = 164; with lead 7 the object is warm on w = 157..164 and cold before and
    after (Glacier Instant's 90-day minimum is clear on both sides)."""
    reads = np.zeros((1, 1100))
    reads[0, 600] = 1
    scn = _scn("aws", reads, 800, 300)
    pol = TwoTier("aws", "seasonal", "standard", "glacier_instant", "move", lead=7, recency=0)
    names = _names(scn, pol.tiers(scn)[0])
    warm = [w for w, t in enumerate(names) if t == "standard"]
    assert warm == list(range(157, 165))
    assert set(names) == {"standard", "glacier_instant"}


def test_seasonal_does_not_go_cold_before_a_predicted_read() -> None:
    """Same object, also read at absolute day 900 (w = 100), recency 30: warm from w = 101. At
    w = 131 recency ends but last year shows a read within Glacier Instant's 90-day minimum (at
    w = 164), so it stays warm until after w = 164."""
    reads = np.zeros((1, 1100))
    reads[0, 600] = 1
    reads[0, 900] = 1
    scn = _scn("aws", reads, 800, 300)
    pol = TwoTier("aws", "seasonal", "standard", "glacier_instant", "move", lead=7, recency=30)
    names = _names(scn, pol.tiers(scn)[0])
    warm = [w for w, t in enumerate(names) if t == "standard"]
    assert warm == list(range(101, 165))


def test_reactive_ignores_last_year_and_oracle_sees_the_future() -> None:
    reads = np.zeros((1, 1100))
    reads[0, 600] = 1  # last year: reactive must ignore it
    reads[0, 1000] = 1  # w = 200
    scn = _scn("aws", reads, 800, 300)
    reactive = TwoTier("aws", "reactive", "standard", "glacier_instant", "move", 1, recency=10)
    warm = [w for w, t in enumerate(_names(scn, reactive.tiers(scn)[0])) if t == "standard"]
    assert warm == list(range(201, 211))
    oracle = TwoTier("aws", "oracle", "standard", "glacier_instant", "move", lead=1, recency=0)
    warm = [w for w, t in enumerate(_names(scn, oracle.tiers(scn)[0])) if t == "standard"]
    assert warm == [199, 200]


def test_copy_mode_orders_one_restore_per_predicted_window() -> None:
    reads = np.zeros((2, 1100))
    reads[0, 600] = 1  # predicted window w = 157..164 (lead 7)
    reads[1, 600] = 1
    scn = _scn("aws", reads, 800, 300, sizes=[BIG, 1000])  # object 1 is under 128 KB
    pol = TwoTier("aws", "seasonal", "standard", "deep_archive", "copy", lead=7, recency=0)
    tier = np.full((2, 300), scn.tier_index("deep_archive"))
    tier[1] = 0
    orders = pol.restores(scn, tier)
    assert [(o.obj, o.day, o.keep_days) for o in orders] == [(0, 157, 8)]
    result = pol.run(scn)  # the run itself passes the AWS rule check
    assert result.waits.cold_reads == 0


def test_small_objects_stay_in_standard_on_aws_only() -> None:
    reads = np.zeros((2, 1100))
    for cloud, cold in [("aws", "deep_archive"), ("gcs", "archive")]:
        scn = _scn(cloud, reads, 800, 300, sizes=[BIG, 1000])
        tier = Lifecycle(cloud, cold).tiers(scn)
        assert (tier[0] == scn.tier_index(cold)).all()
        expected = 0 if cloud == "aws" else scn.tier_index(cold)
        assert (tier[1] == expected).all()


def test_lifecycle_moves_new_objects_after_their_age() -> None:
    reads = np.zeros((1, 1100))
    scn = _scn("gcs", reads, 800, 300, created=[820])
    tier = Lifecycle("gcs", "coldline", after_days=30).tiers(scn)[0]
    names = _names(scn, tier)
    assert names[20:50] == ["standard"] * 30
    assert names[50:] == ["coldline"] * 250


# ------------------------------------------------------------------ Azure last access


def test_azure_last_access_hand_case() -> None:
    """Cool after 5 idle days; the blob exists from day 0 (upload = access on day -1).
    Cool from day 5. Read on day 10 while cool -> hot on day 11. Idle again -> cool on day 16.
    Reads on days 20 and 30 while cool are blocked by the once-in-30-days limit (last move up on
    day 11). Read on day 60 -> hot on day 61."""
    reads = np.zeros((1, 100))
    for day in (10, 20, 30, 60):
        reads[0, day] = 1
    scn = _scn("azure", reads, 0, 100)
    names = _names(scn, AzureLastAccess("azure", 5).tiers(scn)[0])
    assert names[:5] == ["hot"] * 5 and names[5:11] == ["cool"] * 6
    assert names[11:16] == ["hot"] * 5 and names[16] == "cool"
    assert names[21] == "cool" and names[31] == "cool"  # once-in-30-days limit
    assert names[61] == "hot"


def test_azure_cold_and_archive_never_return_by_themselves() -> None:
    reads = np.zeros((1, 400))
    reads[0, 100] = reads[0, 200] = 1
    scn = _scn("azure", reads, 0, 400, created=[0])
    names = _names(scn, AzureLastAccess("azure", 10, cold_days=20, archive_days=60).tiers(scn)[0])
    assert names[95] == "archive"  # idle since day 0
    assert names[101] == "archive" and names[201] == "archive"  # reads do not revive it


# ------------------------------------------------------------------ causality


def _random_history(seed: int, n: int = 25, days: int = 1200) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rates = np.exp(rng.normal(np.log(0.03), 1.5, n))
    season = 1 + 20 * (np.sin(np.arange(days) * 2 * np.pi / 365.25)[None, :] > 0.9)
    out: np.ndarray = rng.poisson(rates[:, None] * season).astype(np.float64)
    return out


CAUSAL = [
    TwoTier("aws", "seasonal", "standard", "deep_archive", "move", 30, 30),
    TwoTier("aws", "seasonal", "glacier_instant", "glacier_flexible", "move", 7, 90),
    TwoTier("gcs", "seasonal", "standard", "archive", "move", 30, 7),
    TwoTier("azure", "reactive", "hot", "cold", "move", 1, 30),
    AzureLastAccess("azure", 30, cold_days=90, archive_days=180),
    Lifecycle("aws", "glacier_flexible"),
]


@pytest.mark.parametrize("pol", CAUSAL, ids=lambda p: p.name)
@pytest.mark.parametrize("cut", [0, 40, 250])
def test_plans_use_only_the_past(pol: TwoTier | AzureLastAccess | Lifecycle, cut: int) -> None:
    """Changing reads from window day ``cut`` on must not change any decision up to that day
    (decisions are made at 00:00, before that day's reads)."""
    reads = _random_history(1)
    sizes = [BIG] * reads.shape[0]
    scn = _scn(pol.cloud, reads, 800, 365, sizes=sizes)
    changed = reads.copy()
    changed[:, 800 + cut :] = np.random.default_rng(2).poisson(0.5, changed[:, 800 + cut :].shape)
    other = _scn(pol.cloud, changed, 800, 365, sizes=sizes)
    a, b = pol.tiers(scn), pol.tiers(other)
    np.testing.assert_array_equal(a[:, : cut + 1], b[:, : cut + 1])
    if isinstance(pol, TwoTier):
        before = [o for o in pol.restores(scn, a) if o.day <= cut]
        assert before == [o for o in pol.restores(other, b) if o.day <= cut]


def test_seasonal_copy_orders_use_only_the_past() -> None:
    pol = TwoTier("azure", "seasonal", "hot", "archive", "copy", 30, 30)
    reads = _random_history(3)
    scn = _scn("azure", reads, 800, 365)
    changed = reads.copy()
    changed[:, 900:] = 0
    other = _scn("azure", changed, 800, 365)
    tier = np.full((reads.shape[0], 365), scn.tier_index("archive"))
    a = [o for o in pol.restores(scn, tier) if o.day <= 100]
    b = [o for o in pol.restores(other, tier) if o.day <= 100]
    assert [(o.obj, o.day) for o in a] == [(o.obj, o.day) for o in b]


def test_last_year_cannot_look_past_yesterday() -> None:
    scn = _scn("aws", _random_history(4), 800, 365)
    scn.last_year_within(0, MAX_AHEAD)
    with pytest.raises(ValueError):
        scn.last_year_within(0, MAX_AHEAD + 1)


# ------------------------------------------------------------------ AWS rules


def test_aws_rule_check_rejects_small_objects_leaving_standard() -> None:
    reads = np.zeros((2, 500))
    scn = _scn("aws", reads, 100, 300, sizes=[BIG, 1000])
    tier = np.zeros((2, 300), dtype=np.int64)
    check_aws_plan(scn, Plan(tier))
    tier[1, 50:] = scn.tier_index("glacier_instant")
    with pytest.raises(PlanRuleError):
        check_aws_plan(scn, Plan(tier))


def test_lifecycle_step_rule_matches_the_aws_example() -> None:
    """AWS docs: Glacier Instant after 4 days, then Deep Archive must be at least day 94."""
    scn = _scn("aws", np.zeros((1, 10)), 0, 10)
    with pytest.raises(PlanRuleError):
        check_lifecycle_steps(scn, [(4, "glacier_instant"), (20, "deep_archive")])
    check_lifecycle_steps(scn, [(4, "glacier_instant"), (94, "deep_archive")])


# ------------------------------------------------------------------ wrappers and costs


def test_intelligent_tiering_policy_is_the_simulator() -> None:
    reads = _random_history(5)
    scn = _scn("aws", reads, 800, 365, measure_from=100)
    pol = IntelligentTiering("aws", archive_days=90)
    a = pol.run(scn)
    b = simulate_intelligent_tiering(
        scn.sheet,
        scn.inventory(),
        scn.window_reads(),
        scn.window_start,
        ITConfig(90, None),
        initial_idle_days=scn.initial_idle_days(),
        measure_from=100,
    )
    assert a.costs == b.costs and a.waits.cold_reads == b.waits.cold_reads


def test_initial_idle_days() -> None:
    reads = np.zeros((3, 200))
    reads[0, 90] = 1  # last read the day before day 91 -> 9 idle days at day 100
    scn = _scn("aws", reads, 100, 50, created=[0, 50, 0])
    assert scn.initial_idle_days().tolist() == [9, 50, 100]
    assert _scn("aws", reads, 0, 50).initial_idle_days().tolist() == [0, 0, 0]


def test_azure_observation_cost_is_one_operation_per_object_day_read() -> None:
    reads = np.zeros((2, 60))
    reads[0, 10] = 5  # five reads in one day: one access-time update
    reads[1, 20] = reads[1, 21] = 1
    scn = _scn("azure", reads, 0, 60)
    plain = Lifecycle("azure", "hot").run(scn)
    tracked = TwoTier("azure", "reactive", "hot", "cool", "move", 1, 365).run(scn)
    fee = PRICES["azure"].extras["other_operations_per_1000"].value / 1000
    assert tracked.costs["monitoring"] == pytest.approx(3 * fee)
    assert plain.costs["monitoring"] == 0


def test_grid_names_are_unique_and_families_complete() -> None:
    for cloud in ("aws", "gcs", "azure"):
        grid = policy_grid(cloud)
        names = [p.name for p in grid]
        assert len(names) == len(set(names))
        families = {p.family for p in grid}
        assert {"lifecycle", "seasonal", "reactive", "oracle"} <= families
        assert ("managed" in families) == (cloud != "azure")
        assert ("access-lifecycle" in families) == (cloud == "azure")


def test_policies_refuse_the_wrong_cloud() -> None:
    scn = _scn("gcs", np.zeros((1, 100)), 10, 50)
    with pytest.raises(ValueError):
        Autoclass("aws").run(scn)
    with pytest.raises(ValueError):
        TwoTier("gcs", "seasonal", "standard", "archive", "copy").run(scn)


# ------------------------------------------------------------------ fee-aware planner, pre-restore


def test_window_sums() -> None:
    reads = np.zeros((1, 1000))
    reads[0, 500] = 3
    reads[0, 520] = 1
    scn = _scn("aws", reads, 800, 100)
    # window day w is absolute 800 + w; last year = absolute 436 + w
    assert scn.last_year_reads_sum(0, 9)[0, 64] == 3  # 436 + 64 = 500
    assert scn.last_year_reads_sum(0, 30)[0, 60] == 4
    assert scn.last_year_read_days_sum(0, 30)[0, 60] == 2
    reads[0, 850] = 2
    scn = _scn("aws", reads, 800, 100)
    assert scn.reads_sum(-5, -1)[0, 52] == 2 and scn.reads_sum(-5, -1)[0, 50] == 0
    assert scn.reads_sum(0, 0)[0, 50] == 2


def test_planner_puts_unread_data_in_the_coldest_class_and_busy_data_in_the_first() -> None:
    reads = np.zeros((2, 1100))
    reads[1] = 3  # read every day
    for kind in ("seasonal", "reactive", "oracle"):
        scn = _scn("gcs", reads, 800, 300)
        pol = Planner("gcs", kind, ("standard", "nearline", "coldline", "archive"), 90, 7)
        tier = pol.tiers(scn)
        assert (tier[0] == scn.tier_index("archive")).all(), kind
        assert (tier[1] == 0).all(), kind


def test_seasonal_planner_warms_archived_data_before_the_predicted_read() -> None:
    """Deep Archive is not allowed within ``lead`` days of a read expected from last year's
    pattern (w = 164 here, as in the warm/cold hand case)."""
    reads = np.zeros((1, 1100))
    reads[0, 600] = 1
    scn = _scn("aws", reads, 800, 300)
    classes = ("standard", "glacier_instant", "deep_archive")
    tier = Planner("aws", "seasonal", classes, 90, lead=7).tiers(scn)[0]
    deep = scn.tier_index("deep_archive")
    assert (tier[157:165] != deep).all()
    assert (tier == deep).any()  # it does use Deep Archive when nothing is expected


@pytest.mark.parametrize(
    "pol",
    [
        Planner("aws", "seasonal", ("standard", "glacier_instant", "deep_archive"), 90, 30),
        Planner("azure", "reactive", ("hot", "cool", "cold", "archive"), 30, 7),
        Planner("gcs", "seasonal", ("standard", "nearline", "coldline", "archive"), 180, 7),
    ],
    ids=lambda p: p.name,
)
@pytest.mark.parametrize("cut", [0, 60, 200])
def test_planner_uses_only_the_past(pol: Planner, cut: int) -> None:
    reads = _random_history(6)
    scn = _scn(pol.cloud, reads, 800, 365)
    changed = reads.copy()
    changed[:, 800 + cut :] = np.random.default_rng(7).poisson(0.4, changed[:, 800 + cut :].shape)
    other = _scn(pol.cloud, changed, 800, 365)
    np.testing.assert_array_equal(pol.tiers(scn)[:, : cut + 1], pol.tiers(other)[:, : cut + 1])


def test_it_prewarm_uses_only_the_past() -> None:
    pol = ITPrewarm("aws", "seasonal", 90, 180, lead=30)
    reads = _random_history(8)
    scn = _scn("aws", reads, 800, 365)
    changed = reads.copy()
    changed[:, 900:] = 5
    other = _scn("aws", changed, 800, 365)
    np.testing.assert_array_equal(pol.prewarm(scn)[:, :101], pol.prewarm(other)[:, :101])


def test_it_prewarm_hand_case() -> None:
    """An object idle for 400 days sits in Deep Archive Access. Read on day 50: without a restore
    it waits 12 hours; restored on day 49 (forecast lead 1) it waits 0, for one POST request."""
    sheet = PRICES["aws"]
    reads = np.zeros((1, 100))
    reads[0, 50] = 1
    inv = Inventory([BIG])
    cfg = ITConfig(90, 180)
    plain = simulate_intelligent_tiering(sheet, inv, reads, HIST, cfg, initial_idle_days=400)
    warm = np.zeros((1, 100), dtype=bool)
    warm[0, 49] = True
    pre = simulate_intelligent_tiering(
        sheet, inv, reads, HIST, cfg, initial_idle_days=400, prewarm=warm
    )
    assert plain.waits.cold_reads == 1 and plain.waits.hours_all_reads == 12
    assert pre.waits.cold_reads == 0
    put = sheet.extras["intelligent_tiering_put_per_1000"].value / 1000
    assert pre.costs["restore_requests"] == pytest.approx(put)
    assert plain.costs["restore_requests"] == 0
    # in Frequent Access on days 49 and 50 instead of Deep Archive Access (without the restore the
    # object only returns to Frequent Access the day after the read): two days of the price gap
    x = {k: p.value for k, p in sheet.extras.items()}
    gap = (
        x["intelligent_tiering_frequent_usd_per_gb_month"]
        - x["intelligent_tiering_deep_archive_access_usd_per_gb_month"]
    )
    feb = date(2016, 2, 19)  # day 49 of a run starting 2016-01-01
    assert (HIST.toordinal() + 49) == feb.toordinal()
    day_factor = 1 / 29
    storage_gap = pre.costs["storage"] + pre.costs["overhead_storage"]
    storage_gap -= plain.costs["storage"] + plain.costs["overhead_storage"]
    over = (32 * x["intelligent_tiering_deep_archive_access_usd_per_gb_month"]) * 1024 / 2**30
    over += 8 * sheet.get("standard", "storage_usd_per_gb_month") * 1024 / 2**30
    assert storage_gap == pytest.approx(2 * (BIG / 2**30 * gap - over) * day_factor, rel=1e-9)


def test_it_prewarm_ignores_objects_that_are_not_archived() -> None:
    sheet = PRICES["aws"]
    reads = np.zeros((1, 60))
    reads[0, 5] = 1
    warm = np.ones((1, 60), dtype=bool)
    r = simulate_intelligent_tiering(
        sheet, Inventory([BIG]), reads, HIST, ITConfig(90, 180), initial_idle_days=0, prewarm=warm
    )
    assert r.costs["restore_requests"] == 0 and r.waits.cold_reads == 0
