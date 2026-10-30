"""Round two (docs/R1_PROTOCOL.md): per-file waits, restore speeds, the per-file chooser and the
gate R1 rules, each on small cases with known answers."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sat.experiments import chooser as ch
from sat.experiments import r1
from sat.policies import IntelligentTiering, Lifecycle, Planner, Scenario, TwoTier, policy_grid
from sat.policies.grid import can_wait, round2_grid
from sat.prices import load_all

PRICES = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices")
GIB = 2**30
HIST = date(2016, 1, 1)


def _scn(reads: np.ndarray, sim_start: int, n_days: int, size: int = GIB) -> Scenario:
    n = reads.shape[0]
    return Scenario(
        "test",
        PRICES["aws"],
        np.full(n, size, dtype=np.int64),
        reads.astype(np.int64),
        np.zeros(n, dtype=np.int64),
        HIST,
        sim_start,
        n_days,
        0,
    )


# ------------------------------------------------------------------ per-file waits


@pytest.mark.parametrize(
    "pol",
    [
        Lifecycle("aws", "deep_archive", 30),
        Lifecycle("aws", "deep_archive", 30, "bulk"),
        IntelligentTiering("aws", 90, 180),
        TwoTier("aws", "reactive", "standard", "glacier_flexible", "copy", 1, 7),
    ],
)
def test_per_file_waits_add_up_to_the_totals(pol: Any) -> None:
    rng = np.random.default_rng(3)
    reads = (rng.random((6, 900)) < 0.01).astype(np.int64) * rng.integers(1, 4, (6, 900))
    scn = _scn(reads, 400, 500)
    res = pol.run(scn)
    assert res.wait_hours_by_object is not None and res.max_wait_by_object is not None
    assert res.wait_hours_by_object.sum() == pytest.approx(res.waits.hours_all_reads)
    assert res.max_wait_by_object.max() == pytest.approx(res.waits.max_hours)


def test_bulk_on_demand_restore_waits_48_hours_and_costs_the_bulk_fee() -> None:
    """One read of a 1 GiB file in Deep Archive: standard waits 12 h and pays 0.02/GB + 0.10/1000;
    bulk waits 48 h and pays 0.0025/GB + 0.025/1000."""
    reads = np.zeros((1, 700))
    reads[0, 650] = 1
    scn = _scn(reads, 400, 300)
    std = Lifecycle("aws", "deep_archive", 30).run(scn)
    bulk = Lifecycle("aws", "deep_archive", 30, "bulk").run(scn)
    assert std.waits.max_hours == 12 and bulk.waits.max_hours == 48
    assert std.costs["retrieval"] == pytest.approx(0.02)
    assert bulk.costs["retrieval"] == pytest.approx(0.0025)
    assert std.costs["restore_requests"] == pytest.approx(0.10 / 1000)
    assert bulk.costs["restore_requests"] == pytest.approx(0.025 / 1000)


def test_bulk_copy_mode_orders_bulk_restores_in_time() -> None:
    """Read every year on the same day: a seasonal copy-mode policy with lead 7 orders a restore a
    week ahead, so at bulk speed (48 h) nothing waits and retrieval is billed at 0.0025/GB."""
    reads = np.zeros((1, 1200))
    for d in (300, 664, 1028):  # 364 days apart
        reads[0, d] = 1
    scn = _scn(reads, 600, 600)
    pol = TwoTier("aws", "seasonal", "standard", "deep_archive", "copy", 7, 7, "bulk")
    res = pol.run(scn)
    assert res.waits.cold_reads == 0
    assert res.costs["retrieval"] == pytest.approx(2 * 0.0025)


def test_e1_grid_is_unchanged_and_round_two_names_are_unique() -> None:
    e1 = [p.name for p in policy_grid("aws")]
    assert len(e1) == 140 and not any("bulk" in n for n in e1)
    names = [p.name for p in round2_grid("aws")]
    assert len(names) == len(set(names)) == 161
    assert "intelligent-tiering" in names
    assert not any(n.startswith("oracle") for n in names)


def test_can_wait() -> None:
    assert not can_wait(IntelligentTiering("aws"))
    assert can_wait(IntelligentTiering("aws", 90))
    assert not can_wait(Lifecycle("aws", "glacier_instant", 30))
    assert can_wait(Lifecycle("aws", "glacier_flexible", 30))
    assert not can_wait(Planner("aws", "seasonal", ("standard", "standard_ia", "glacier_instant")))
    assert can_wait(Planner("aws", "seasonal", ("standard", "glacier_instant", "deep_archive")))
    assert can_wait(TwoTier("aws", "seasonal", "standard", "deep_archive"))


def test_unknown_speed_is_refused() -> None:
    with pytest.raises(ValueError):
        TwoTier("aws", "seasonal", "standard", "deep_archive", speed="expedited")
    with pytest.raises(ValueError):
        Lifecycle("aws", "deep_archive", 30, "fast")


# ------------------------------------------------------------------ chooser


def test_switch_charge_is_the_aws_upper_bound() -> None:
    """Worst read-out 0.03/GB (Glacier Instant retrieval), worst early deletion 30 days at
    0.0125 (Standard-IA) = 0.0125/GB, worst request 0.10/1000 (Deep Archive standard restore)."""
    got = ch.switch_charge(PRICES["aws"], np.array([GIB, 0], dtype=np.int64) + np.array([0, 1]))
    assert got[0] == pytest.approx(0.03 + 0.0125 + 0.10 / 1000)
    assert got[1] == pytest.approx(0.10 / 1000, rel=1e-6)


def _choose(**kw: Any) -> np.ndarray:
    base: dict[str, Any] = {
        "cost": np.array([[10.0, 10.0, 10.0], [5.0, 9.5, 20.0], [1.0, 1.0, 1.0]]),
        "cold": np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [3.0, 3.0, 3.0]]),
        "allowed": np.array([True, True, True]),
        "prior": np.array([0, 0, 0]),
        "has_history": np.array([True, True, False]),
        "switch": np.zeros(3),
        "setting": ch.Setting("all", 10.0, 0.0),
    }
    base.update(kw)
    return ch.choose(**base)


def test_chooser_picks_lowest_score_and_keeps_files_without_history() -> None:
    # policy 2 costs 1 but 3 waited reads x mu 10 = 31; file 2 has no history: stays on default
    assert _choose().tolist() == [1, 1, 0]
    assert _choose(setting=ch.Setting("all", 0.0, 0.0)).tolist() == [2, 2, 0]


def test_chooser_margin_and_switch_charge_keep_the_current_policy() -> None:
    # file 1: 9.5 vs 10 is only 5% better, below a 10% margin
    assert _choose(setting=ch.Setting("all", 10.0, 0.1)).tolist() == [1, 0, 0]
    # a switch charge of 1 makes file 1's move (9.5 + 1 > 10) not worth it
    assert _choose(switch=np.ones(3)).tolist() == [1, 0, 0]


def test_chooser_menu() -> None:
    allowed = np.array([True, False, True])
    assert _choose(allowed=allowed, setting=ch.Setting("online", 0.0, 0.0)).tolist() == [2, 2, 0]
    with pytest.raises(ValueError):
        _choose(allowed=np.array([False, True, True]))


def test_outcome_bills_each_file_under_its_policy_and_charges_switches() -> None:
    cost = np.array([[1.0, 2.0], [3.0, 4.0]])
    cold = np.array([[0.0, 1.0], [2.0, 0.0]])
    hours = np.array([[0.0, 12.0], [96.0, 0.0]])
    maxw = np.array([[0.0, 12.0], [48.0, 0.0]])
    o = ch.outcome(
        cost,
        cold,
        hours,
        maxw,
        np.array([5.0, 5.0]),
        np.array([1, 0]),
        np.array([0, 0]),
        np.array([0.5, 0.7]),
    )
    assert o.cost == pytest.approx(3.0 + 2.0 + 0.5)
    assert o.cold_reads == 3.0 and o.cold_rate == pytest.approx(0.3)
    assert o.wait_hours == 108.0 and o.max_wait_hours == 48.0
    assert o.switches == 1 and o.switch_cost == 0.5


# ------------------------------------------------------------------ R1 rules


def test_rolling_scenario_cuts_reads_at_the_end_of_the_measured_year() -> None:
    scn, keep = r1.scenario(r1.DEV, 2020, "actual")
    f = r1.files(r1.DEV, "actual")
    assert scn.reads.shape[1] == (date(2020, 12, 31) - f.start).days + 1
    assert scn.window_start == date(2019, 1, 1)
    assert scn.measure_from == 365
    assert (scn.created < scn.end).all() and len(keep) == scn.n_objects
    with pytest.raises(ValueError):
        r1.scenario(r1.DEV, 2023, "actual")


def test_replicate_draw_differs_from_the_actual_draw() -> None:
    a, b = r1.files(r1.DEV, "actual"), r1.files(r1.DEV, "replicate")
    assert a.reads.shape == b.reads.shape and not np.array_equal(a.reads, b.reads)


def _line(dataset: str, pair: int, level: str, **kw: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "dataset": dataset,
        "pick_year": r1.PAIRS[pair][0],
        "score_year": r1.PAIRS[pair][1],
        "level": level,
        "rule": "matched",
        "ours_policy": "x",
        "ours_gap": 0.06,
        "ours_wait_ok": True,
        "ceiling_policy": "y",
        "ceiling_gap": 0.11,
        "ceiling_wait_ok": True,
        "r2_closed": 0.6,
    }
    line.update(kw)
    return line


def test_r1_needs_both_rolling_years_at_one_level_on_two_datasets() -> None:
    good = [_line(d, p, "L1") for d in ("D1", "D3") for p in (0, 1)]
    assert r1.verdict(good)["R1"] and r1.verdict(good)["R2"]
    # one rolling year fails on D3: only D1 holds, R1 fails
    bad = good[:3] + [_line("D3", 1, "L1", ours_gap=0.04)]
    assert not r1.verdict(bad)["R1"]
    # passing in different levels for the two years does not count
    mixed = good[:2] + [_line("D3", 0, "L0"), _line("D3", 1, "L1")]
    assert not r1.verdict(mixed)["R1"]
    # waiting more than the rival fails the line
    waits = good[:3] + [_line("D3", 1, "L1", ours_wait_ok=False)]
    assert not r1.verdict(waits)["R1"]
    # the ceiling must clear 10%
    ceiling = [_line(d, p, "L1", ceiling_gap=0.09) for d in ("D1", "D3") for p in (0, 1)]
    assert not r1.verdict(ceiling)["R1"]
    # equal-allowance lines never decide
    equal = [dict(x, rule="equal") for x in good]
    assert not r1.verdict(equal)["R1"]


def test_lines_pick_on_the_pick_year_and_score_on_the_next() -> None:
    import polars as pl

    rows = []
    for year, (rival_cost, ours_cost) in {2020: (10.0, 9.0), 2021: (10.0, 9.4)}.items():
        rows += [
            {
                "dataset": "D1",
                "year": year,
                "policy": "riv",
                "family": "managed",
                "rival": True,
                "cost": rival_cost,
                "cold_rate": 0.0,
                "wait_hours_all": 0.0,
                "wait_max_hours": 0.0,
            },
            {
                "dataset": "D1",
                "year": year,
                "policy": "ours",
                "family": "seasonal",
                "rival": False,
                "cost": ours_cost,
                "cold_rate": 0.0,
                "wait_hours_all": 0.0,
                "wait_max_hours": 0.0,
            },
            {
                "dataset": "D1",
                "year": year,
                "policy": "cheap-waits",
                "family": "chooser",
                "rival": False,
                "cost": 2.0,
                "cold_rate": 0.005,
                "wait_hours_all": 6.0,
                "wait_max_hours": 12.0,
            },
            {
                "dataset": "D1",
                "year": year,
                "policy": "ceil",
                "family": "ceiling",
                "rival": False,
                "cost": 0.5,
                "cold_rate": 0.0,
                "wait_hours_all": 0.0,
                "wait_max_hours": 0.0,
            },
            {
                "dataset": "D1",
                "year": year,
                "policy": "waits",
                "family": "chooser",
                "rival": False,
                "cost": 1.0,
                "cold_rate": 0.5,
                "wait_hours_all": 9.0,
                "wait_max_hours": 12.0,
            },
        ]
    table = pl.DataFrame(rows)
    saved = r1.PAIRS
    r1.PAIRS = ((2020, 2021),)  # type: ignore[assignment]
    try:
        out = r1.lines(table)
    finally:
        r1.PAIRS = saved
    matched = [x for x in out if x["rule"] == "matched" and x["level"] == "L1"]
    assert len(matched) == 1
    assert matched[0]["ours_policy"] == "ours"  # "waits" breaks the rival's 0% wait
    assert matched[0]["ours_gap"] == pytest.approx(0.06)
    assert matched[0]["ceiling_policy"] == "ceil"
    # the equal-allowance rule lets ours wait up to 1% even though the rival waited 0%
    equal = [x for x in out if x["rule"] == "equal" and x["level"] == "L1"]
    assert equal[0]["ours_policy"] == "cheap-waits" and not equal[0]["ours_wait_ok"]


def test_chooser_history_is_the_year_before(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[int, str]] = []
    names = [ch.DEFAULT_POLICY, "other"]

    def fake(dataset: str, year: int, draw: str) -> r1.Run:
        asked.append((year, draw))
        one = np.ones((2, 2))
        return r1.Run(
            names,
            np.array([0, 1]),
            np.array([GIB, GIB]),
            np.ones(2),
            one,
            0 * one,
            0 * one,
            0 * one,
            np.array([False, False]),
        )

    monkeypatch.setattr(r1, "load_run", fake)
    r1.chooser_choices("D1", 2021, "chooser", ch.SETTINGS[0], None)
    assert asked == [(2021, "actual"), (2020, "actual")]
    asked.clear()
    r1.chooser_choices("D1", 2021, "ceiling", ch.SETTINGS[0], None)
    assert asked == [(2021, "actual"), (2021, "replicate")]


DATA = Path(__file__).resolve().parents[1] / "data" / "processed" / "D3"


@pytest.mark.skipif(not DATA.exists(), reason="needs the processed D3 data")
def test_actual_draw_is_the_e1_central_draw_and_the_replicate_is_not() -> None:
    from sat.experiments import e1

    central = e1.load_objects("D3", 2022, "central")
    actual, replicate = r1.files("D3", "actual"), r1.files("D3", "replicate")
    assert np.array_equal(actual.reads, central.reads)
    assert np.array_equal(actual.sizes, central.sizes)
    assert not np.array_equal(replicate.reads, actual.reads)
    assert np.array_equal(replicate.created, actual.created)


# ------------------------------------------------------------------ Azure ZRS and smart tier

ZRS = load_all(Path(__file__).resolve().parents[1] / "configs" / "prices" / "azure_zrs")["azure"]


def test_zrs_sheet_is_fully_sourced_and_has_no_archive() -> None:
    assert ZRS.unverified() == []
    assert ZRS.tier_order == ("hot", "cool", "cold")
    assert ZRS.get("hot", "storage_usd_per_gb_month") == 0.023


def test_smart_tier_hand_case() -> None:
    """A 1 GiB object, idle for years, read once on day 100 of a 200-day window. Before the read
    it is cold (90 or more idle days); the read day and the 30 days without access after it are
    hot, then 60 days cool (30 to 89 idle days), then cold. Storage uses the sheet's daily factor.
    Reads cost the hot rate; transitions, retrieval and early deletion are free."""
    from sat.policies import SmartTier
    from sat.sim.rules import daily_storage_factor, rules_for

    reads = np.zeros((1, 1200))
    reads[0, 1100] = 1
    scn = Scenario(
        "t", ZRS, np.array([GIB]), reads.astype(np.int64), np.array([0]), HIST, 1000, 200, 0
    )
    res = SmartTier("azure").run(scn)
    factor = daily_storage_factor(rules_for(ZRS), scn.window_start, 200)
    tiers = np.array([0.004] * 100 + [0.023] * 31 + [0.0125] * 60 + [0.004] * 9)
    assert res.costs["storage"] == pytest.approx(float((tiers * factor).sum()))
    assert res.costs["read_requests"] == pytest.approx(0.004 / 10_000)
    assert res.costs["retrieval"] == 0 and res.costs["transition"] == 0
    assert res.costs["early_delete"] == 0 and res.waits.cold_reads == 0
    assert res.costs["monitoring"] == pytest.approx(200 * 0.04 / 10_000 / 30)


def test_smart_tier_small_objects_stay_hot_without_a_fee() -> None:
    from sat.policies import SmartTier

    reads = np.zeros((1, 1200), dtype=np.int64)
    scn = Scenario("t", ZRS, np.array([1000]), reads, np.array([0]), HIST, 1000, 200, 0)
    res = SmartTier("azure").run(scn)
    assert res.costs["monitoring"] == 0
    assert res.costs["storage"] > 0


def test_zrs_grid_runs_without_an_archive_tier() -> None:
    from sat.policies.grid import zrs_grid

    reads = (np.random.default_rng(1).random((3, 900)) < 0.02).astype(np.int64)
    scn = Scenario("t", ZRS, np.full(3, GIB), reads, np.zeros(3, dtype=np.int64), HIST, 400, 500, 0)
    names = set()
    for pol in zrs_grid():
        res = pol.run(scn)
        assert res.waits.cold_reads == 0
        names.add(pol.name)
    assert "smart-tier" in names and len(names) == len(zrs_grid())
