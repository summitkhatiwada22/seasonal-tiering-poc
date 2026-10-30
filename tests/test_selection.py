"""E1 selection rule and hindsight bound on small hand-made inputs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from sat.experiments.select import hindsight, pick


def _frame(rows: list[tuple[str, str, bool, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows, schema=["policy", "family", "rival", "cost", "cold_rate"], orient="row"
    ).with_columns(pl.lit("D1").alias("dataset"), pl.lit("aws").alias("cloud"))


def test_pick_matches_the_protocol() -> None:
    tune = _frame(
        [
            ("all-standard", "lifecycle", True, 100.0, 0.0),
            ("it", "managed", True, 80.0, 0.0),
            ("it-archive", "managed", True, 60.0, 0.005),
            ("deep", "lifecycle", True, 30.0, 0.9),
            ("s-instant", "seasonal", False, 75.0, 0.0),
            ("s-archive-a", "seasonal", False, 50.0, 0.004),
            ("s-archive-b", "seasonal", False, 45.0, 0.006),  # cheaper but waits more than rival
            ("r-instant", "reactive", False, 79.0, 0.0),
        ]
    )
    got = {(p["level"], p["role"]): p["policy"] for p in pick(tune)}
    assert got[("L0", "rival")] == "it"  # cheapest rival with no waiting read
    assert got[("L0", "seasonal")] == "s-instant"
    assert got[("L0", "reactive")] == "r-instant"
    assert got[("L1", "rival")] == "it-archive"  # cheapest rival with at most 1% waiting
    assert got[("L1", "seasonal")] == "s-archive-a"  # no more waiting than the rival
    assert ("L1", "reactive") in got and got[("L1", "reactive")] == "r-instant"


def test_hindsight_bound_hand_case() -> None:
    # plans x objects
    cost = np.array([[10.0, 10.0, 10.0], [4.0, 12.0, 9.0], [2.0, 1.0, 9.5]])
    cold = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 3.0, 0.0]])
    reads = np.array([10.0, 10.0, 10.0])
    # no waiting allowed: object 0 -> 4, object 1 -> 10, object 2 -> 9
    assert hindsight(cost, cold, reads, 0.0) == pytest.approx(23.0)
    # one waiting read allowed: switch object 0 to plan 2 (saves 2 for 1 waiting read)
    assert hindsight(cost, cold, reads, 1.0) == pytest.approx(21.0)
    # four allowed: both switches (object 1 saves 9 for 3 waiting reads)
    assert hindsight(cost, cold, reads, 4.0) == pytest.approx(12.0)


def _write_eval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    costs: dict[str, tuple[float, float, float]],
) -> None:
    """Hand-made 2023 results: dataset -> (rival cost, seasonal cost, seasonal cold rate)."""
    import json

    import sat.experiments.e1 as e1
    import sat.experiments.select as sel

    reports = tmp_path / "reports"
    monkeypatch.setattr(e1, "REPORTS", reports)
    monkeypatch.setattr(sel, "REPORTS", reports)
    monkeypatch.setattr(sel, "REPO", tmp_path)
    (reports / "central" / "eval").mkdir(parents=True)
    (tmp_path / "data" / "e1" / "central" / "eval").mkdir(parents=True)
    picks: list[dict[str, object]] = []
    for dataset, (rc, sc, s_cold) in costs.items():
        for role, name in (("rival", "r"), ("seasonal", "s"), ("reactive", "x")):
            picks.append(
                {
                    "dataset": dataset,
                    "cloud": "aws",
                    "level": "L0",
                    "role": role,
                    "policy": name,
                    "tune_cost": 1.0,
                    "tune_cold_rate": 0.0,
                }
            )
        rows = [
            ("r", "managed", True, rc, 0.0),
            ("s", "seasonal", False, sc, s_cold),
            ("x", "reactive", False, rc, 0.0),
            ("o", "oracle", False, 0.5 * rc, 0.0),
        ]
        frame = pl.DataFrame(
            rows, schema=["policy", "family", "rival", "cost", "cold_rate"], orient="row"
        )
        frame = frame.with_columns(pl.lit(dataset).alias("dataset"), pl.lit("aws").alias("cloud"))
        frame.write_parquet(reports / "central" / "eval" / f"{dataset}_aws.parquet")
        np.savez(
            tmp_path / "data" / "e1" / "central" / "eval" / f"{dataset}_aws.npz",
            names=np.array(["r", "s", "x", "o"]),
            cost=np.array([[rc], [sc], [rc], [0.5 * rc]]),
            cold=np.zeros((4, 1)),
            reads=np.array([10.0]),
        )
    (reports / "central" / "picks.json").write_text(json.dumps({"picks": picks}))


def test_verdict_follows_the_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sat.experiments.select import verdict

    # D1: 10% cheaper, no waiting -> passes. D3: 10% cheaper but waits more -> fails.
    # D4: 4% cheaper -> fails (below 5%).
    _write_eval(
        tmp_path,
        monkeypatch,
        {"D1": (100.0, 90.0, 0.0), "D3": (100.0, 90.0, 0.02), "D4": (100.0, 96.0, 0.0)},
    )
    out = verdict("central")
    assert out["real_datasets_passing"] == ["D1"]
    assert out["decision"] == "CONTINUE"
    lines = {x["dataset"]: x for x in out["lines"]}
    assert lines["D1"]["seasonal_gap"] == pytest.approx(0.10)
    assert lines["D3"]["seasonal_wait_ok"] is False
    assert lines["D1"]["perfect_forecast_gap"] == pytest.approx(0.5)
    assert lines["D1"]["seasonal_vs_reactive"] == pytest.approx(0.10)


def test_verdict_stops_when_no_real_dataset_reaches_five_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sat.experiments.select import verdict

    _write_eval(tmp_path, monkeypatch, {"D1": (100.0, 95.5, 0.0), "D7": (100.0, 50.0, 0.0)})
    out = verdict("central")
    assert out["real_datasets_passing"] == []  # D7 is synthetic: it never counts
    assert out["decision"] == "STOP AND RETHINK"
