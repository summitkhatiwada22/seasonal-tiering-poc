"""E1 selection rule and hindsight bound on small hand-made inputs."""

from __future__ import annotations

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
