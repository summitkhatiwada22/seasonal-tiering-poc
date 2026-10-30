"""Early check E1: run every policy on every dataset and cloud, tune on 2022, score on 2023.

The rules are fixed in docs/E1_PROTOCOL.md before any 2023 number is computed. This module only
does what the protocol says:

* ``tune``: simulate 2021-2022 (2021 is warm-up) with data up to 2022 only, measure 2022.
* ``eval``: simulate 2022-2023 (2022 is warm-up) with data up to 2023, measure 2023.

Command line (results go to ``reports/e1/<run>/``):

    python -m sat.experiments.e1 run --period tune --setting central
    python -m sat.experiments.e1 pick --setting central
    python -m sat.experiments.e1 run --period eval --setting central
    python -m sat.experiments.e1 verdict --setting central
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from sat.data.demand import Demand, load_d1, load_d3, load_d4
from sat.data.mapping import READ_SEED, default_scales, to_reads
from sat.data.sealed import TUNING_YEAR, VALIDATION_YEAR
from sat.data.sizes import draw_u, sizes_for
from sat.policies import RIVAL_FAMILIES, Policy, Scenario, policy_grid
from sat.prices import PriceSheet, load_all
from sat.synth import SynthConfig, generate

REPO = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("SAT_DATA", REPO / "data" / "processed"))
REPORTS = REPO / "reports" / "e1"
PRICES: dict[str, PriceSheet] = load_all(REPO / "configs" / "prices")

REAL = ("D1", "D3", "D4")
SYNTH = ("D7", "D7-control")
CLOUDS = ("aws", "gcs", "azure")
LEVELS = {"L0": 0.0, "L1": 0.01}  # largest share of reads allowed to wait
DATASET_CODE = {"D1": 1, "D3": 3, "D4": 4}
SETTINGS: dict[str, dict[str, Any]] = {
    "central": {"size": "central", "reads": "central", "seed": 1, "restore": "high"},
    "size-low": {"size": "low", "reads": "central", "seed": 1, "restore": "high"},
    "size-high": {"size": "high", "reads": "central", "seed": 1, "restore": "high"},
    "reads-low": {"size": "central", "reads": "low", "seed": 1, "restore": "high"},
    "reads-high": {"size": "central", "reads": "high", "seed": 1, "restore": "high"},
    # evaluated with the central picks only (no re-tuning):
    "restore-low": {"size": "central", "reads": "central", "seed": 1, "restore": "low"},
    "seed-2": {"size": "central", "reads": "central", "seed": 2, "restore": "high"},
    "seed-3": {"size": "central", "reads": "central", "seed": 3, "restore": "high"},
}
PICKS_FROM = {"restore-low": "central", "seed-2": "central", "seed-3": "central"}
PERIODS = {
    # period -> (max data year, first simulated day, first measured day)
    "tune": (TUNING_YEAR, date(TUNING_YEAR - 1, 1, 1), date(TUNING_YEAR, 1, 1)),
    "eval": (VALIDATION_YEAR, date(VALIDATION_YEAR - 1, 1, 1), date(VALIDATION_YEAR, 1, 1)),
}

FloatArray = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------- scenarios


@dataclass(frozen=True)
class Objects:
    """One dataset's objects for one setting: reads, creation days, sizes, groups."""

    name: str
    hist_start: date
    reads: npt.NDArray[np.int64]
    created: npt.NDArray[np.int64]
    sizes: npt.NDArray[np.int64]
    groups: dict[str, npt.NDArray[np.bool_]]


@cache
def _demand(dataset: str, max_year: int) -> Demand:
    if dataset == "D1":
        return load_d1(DATA, max_year)
    if dataset == "D3":
        return load_d3(DATA, max_year)
    if dataset == "D4":
        return load_d4(DATA / "D4_sample", max_year)
    raise ValueError(dataset)


def load_objects(dataset: str, max_year: int, setting: str) -> Objects:
    cfg = SETTINGS[setting]
    if dataset in SYNTH:
        data = generate(SynthConfig(n_objects=10_000, seed=42, seasonality=dataset == "D7"))
        objs = data.objects
        start = date(2021, 1, 1)
        n_days = (date(max_year, 12, 31) - start).days + 1
        reads = np.zeros((objs.height, n_days), dtype=np.int64)
        r = data.reads.with_columns((pl.col("date") - pl.lit(start)).dt.total_days().alias("d"))
        r = r.filter(pl.col("d") < n_days)
        reads[r["object_id"].to_numpy(), r["d"].to_numpy()] = r["reads"].to_numpy()
        category = objs["category"].to_numpy()
        groups = {c: category == c for c in np.unique(category)}
        created = objs["created_day"].to_numpy().astype(np.int64)
        sizes = objs["size_bytes"].to_numpy().astype(np.int64)
        return Objects(dataset, start, reads, created, sizes, groups)
    demand = _demand(dataset, max_year)
    seed = READ_SEED + int(cfg["seed"]) - 1
    reads = to_reads(demand, default_scales(demand, cfg["reads"]), cfg["reads"], seed=seed)
    sizes = sizes_for(draw_u(len(demand.names), DATASET_CODE[dataset]), cfg["size"])
    return Objects(dataset, demand.start, reads, demand.first_demand_day(), sizes, demand.groups)


def scenario(objs: Objects, cloud: str, period: str, setting: str) -> tuple[Scenario, FloatArray]:
    """The scenario and the mask of objects kept (those that exist by the window's end)."""
    _, first_day, measured_day = PERIODS[period]
    sim_start = (first_day - objs.hist_start).days
    measure = (measured_day - first_day).days
    n_days = objs.reads.shape[1] - sim_start
    keep = objs.created < sim_start + n_days
    scn = Scenario(
        objs.name,
        PRICES[cloud],
        objs.sizes[keep],
        objs.reads[keep],
        objs.created[keep],
        objs.hist_start,
        sim_start,
        n_days,
        measure,
        restore_time=SETTINGS[setting]["restore"],
    )
    return scn, keep


# ---------------------------------------------------------------------------- running


def _row(pol: Policy, scn: Scenario, result: Any, elapsed: float) -> dict[str, Any]:
    costs = result.costs_from(scn.measure_from)
    w = result.waits
    return {
        "policy": pol.name,
        "family": pol.family,
        "rival": pol.family in RIVAL_FAMILIES,
        "params": json.dumps(pol.params(), sort_keys=True),
        "cost": float(sum(costs.values())),
        **{f"cost_{k}": v for k, v in costs.items()},
        "reads": w.reads,
        "cold_reads": w.cold_reads,
        "cold_rate": w.share_waited(),
        "wait_hours_all": w.hours_all_reads,
        "wait_hours_first": w.hours_first_read,
        "wait_p99_hours": w.percentile_hours(99),
        "wait_max_hours": w.max_hours,
        "seconds": elapsed,
    }


def run_job(
    dataset: str, cloud: str, period: str, setting: str, only: Iterable[str] | None
) -> Path:
    max_year = PERIODS[period][0]
    objs = load_objects(dataset, max_year, setting)
    scn, keep = scenario(objs, cloud, period, setting)
    wanted = set(only) if only is not None else None
    rows, per_obj, cold_obj = [], [], []
    for pol in policy_grid(cloud):
        if wanted is not None and pol.name not in wanted:
            continue
        t0 = time.time()
        result = pol.run(scn)
        rows.append(_row(pol, scn, result, time.time() - t0))
        per_obj.append(result.per_object_measured)
        cold_obj.append(result.cold_by_object)
    out = REPORTS / setting / period
    out.mkdir(parents=True, exist_ok=True)
    meta = {"dataset": dataset, "cloud": cloud, "period": period, "setting": setting}
    frame = pl.DataFrame(rows).with_columns(*[pl.lit(v).alias(k) for k, v in meta.items()])
    frame.write_parquet(out / f"{dataset}_{cloud}.parquet")
    groups = {k: v[keep] for k, v in objs.groups.items()}
    work = REPO / "data" / "e1" / setting / period
    work.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        work / f"{dataset}_{cloud}.npz",
        names=np.array([r["policy"] for r in rows]),
        cost=np.array(per_obj, dtype=np.float64),
        cold=np.array(cold_obj, dtype=np.float64),
        reads=scn.window_reads()[:, scn.measure_from :].sum(axis=1).astype(np.float64),
        **{f"group_{k}": v for k, v in groups.items()},
    )
    return out / f"{dataset}_{cloud}.parquet"


def run(period: str, setting: str, datasets: Iterable[str], workers: int) -> None:
    if setting in PICKS_FROM and period == "tune":
        raise ValueError(f"{setting} uses the {PICKS_FROM[setting]} picks; it has no tuning run")
    only: list[str] | None = None
    jobs = [(d, c) for d in datasets for c in CLOUDS]
    picks_file = REPORTS / PICKS_FROM.get(setting, setting) / "picks.json"
    # Validation runs score the picks only, except at the central setting, where every policy is
    # run because the hindsight bound and the perfect-forecast line need them (protocol section 5).
    if setting in PICKS_FROM or (period == "eval" and setting != "central"):
        if not picks_file.exists():
            raise FileNotFoundError(f"{picks_file}: pick on 2022 (and commit) before validating")
        picks = json.loads(picks_file.read_text())
        only = sorted({p["policy"] for p in picks["picks"]})
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_job, d, c, period, setting, only) for d, c in jobs]
        for fut in futures:
            print("wrote", fut.result(), flush=True)


def results(setting: str, period: str) -> pl.DataFrame:
    return pl.concat(
        [pl.read_parquet(p) for p in sorted((REPORTS / setting / period).glob("*.parquet"))],
        how="diagonal",
    )
