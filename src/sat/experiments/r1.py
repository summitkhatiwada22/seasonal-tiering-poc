"""Gate R1 (round two): rolling years on AWS, exactly as docs/R1_PROTOCOL.md states.

Years are measured one at a time: year Y is simulated from 1 January of Y-1 (warm-up) to
31 December of Y and measured over Y. Data are loaded up to 2022 only (2023 is used, 2024 and
2025 are sealed) and the reads matrix is cut at the end of Y, so no policy can see past year Y.

* ``actual`` draw: the reads every result is scored on (the E1 central setting).
* ``replicate`` draw: an independent draw from the same true expected rates (seed + 100). Only the
  forecastable ceiling uses it, to choose; nothing is scored on it.

Command line (results in ``reports/r1/``, per-file arrays in ``data/r1/``):

    python -m sat.experiments.r1 run --datasets D1 D3 D4 --years 2019 2020 2021 2022 --draw actual
    python -m sat.experiments.r1 run --datasets D1 D3 D4 --years 2020 2021 2022 --draw replicate
    python -m sat.experiments.r1 score
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from sat.data.mapping import READ_SEED, default_scales, to_reads
from sat.data.sealed import TUNING_YEAR
from sat.data.sizes import draw_u, sizes_for
from sat.experiments import chooser as ch
from sat.experiments.e1 import DATASET_CODE, PRICES, REPO, _demand, _row
from sat.policies import Scenario
from sat.policies.grid import can_wait, round2_grid
from sat.synth import SynthConfig, generate

REPORTS = REPO / "reports" / "r1"
WORK = REPO / "data" / "r1"
CLOUD = "aws"
REAL = ("D1", "D3", "D4")
DEV = "D7"  # synthetic, for development only; never part of the verdict
DATA_MAX_YEAR = TUNING_YEAR  # 2022: nothing later is ever loaded here
REPLICATE_OFFSET = 100
PAIRS = ((2020, 2021), (2021, 2022))  # (pick year, score year)
LEVELS = {"L0": 0.0, "L1": 0.01}
GAP_METHOD = 0.05  # R1 condition 1
GAP_CEILING = 0.10  # R1 condition 2
CLOSE_R2 = 0.5  # R2: share of the reactive-to-ceiling gap a forecast must close
TOL = 1e-12
OURS = ("seasonal", "chooser")  # families that count as "a method" of ours

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]


# ---------------------------------------------------------------------------- data


@dataclass(frozen=True)
class Files:
    start: date
    reads: IntArray
    created: IntArray
    sizes: IntArray


@cache
def files(dataset: str, draw: str) -> Files:
    if draw not in {"actual", "replicate"}:
        raise ValueError(draw)
    if dataset == DEV:
        if draw == "replicate":  # development stand-in: the generator has no rate to redraw from
            base = files(dataset, "actual")
            rng = np.random.default_rng(REPLICATE_OFFSET)
            return Files(base.start, rng.poisson(base.reads), base.created, base.sizes)
        start = date(2018, 1, 1)
        cfg = SynthConfig(
            n_objects=3_000, start=start, n_days=(date(DATA_MAX_YEAR, 12, 31) - start).days + 1
        )
        data = generate(cfg)
        objs = data.objects
        reads = np.zeros((objs.height, cfg.n_days), dtype=np.int64)
        r = data.reads.with_columns((pl.col("date") - pl.lit(start)).dt.total_days().alias("d"))
        reads[r["object_id"].to_numpy(), r["d"].to_numpy()] = r["reads"].to_numpy()
        return Files(
            start,
            reads,
            objs["created_day"].to_numpy().astype(np.int64),
            objs["size_bytes"].to_numpy().astype(np.int64),
        )
    demand = _demand(dataset, DATA_MAX_YEAR)
    seed = READ_SEED + (REPLICATE_OFFSET if draw == "replicate" else 0)
    reads = to_reads(demand, default_scales(demand, "central"), "central", seed=seed)
    sizes = sizes_for(draw_u(len(demand.names), DATASET_CODE[dataset]), "central")
    return Files(demand.start, reads, demand.first_demand_day(), sizes)


def scenario(dataset: str, year: int, draw: str) -> tuple[Scenario, IntArray]:
    """Year ``year`` measured, ``year - 1`` warm-up; reads cut at the end of ``year``."""
    if not 2017 <= year <= DATA_MAX_YEAR:
        raise ValueError(f"year {year} is outside the rolling years")
    f = files(dataset, draw)
    sim_start = (date(year - 1, 1, 1) - f.start).days
    end = (date(year, 12, 31) - f.start).days + 1
    measure = (date(year, 1, 1) - date(year - 1, 1, 1)).days
    keep = np.flatnonzero(f.created < end)
    scn = Scenario(
        dataset,
        PRICES[CLOUD],
        f.sizes[keep],
        f.reads[keep, :end],
        f.created[keep],
        f.start,
        sim_start,
        end - sim_start,
        measure,
    )
    return scn, keep.astype(np.int64)


def _stem(dataset: str, year: int, draw: str) -> str:
    return f"{dataset}_{year}_{draw}"


def run_one(dataset: str, year: int, draw: str) -> Path:
    scn, keep = scenario(dataset, year, draw)
    pols = round2_grid(CLOUD)
    rows: list[dict[str, Any]] = []
    arrays: dict[str, list[FloatArray]] = {k: [] for k in ("cost", "cold", "hours", "maxw")}
    for pol in pols:
        t0 = time.time()
        res = pol.run(scn)
        row = _row(pol, scn, res, time.time() - t0)
        row["can_wait"] = can_wait(pol)
        rows.append(row)
        for key, values in (
            ("cost", res.per_object_measured),
            ("cold", res.cold_by_object),
            ("hours", res.wait_hours_by_object),
            ("maxw", res.max_wait_by_object),
        ):
            if values is None:
                raise ValueError(f"{pol.name}: the simulator returned no per-file {key}")
            arrays[key].append(values)
    (REPORTS / "runs").mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    meta = {"dataset": dataset, "year": year, "draw": draw}
    frame = pl.DataFrame(rows).with_columns(*[pl.lit(v).alias(k) for k, v in meta.items()])
    out = REPORTS / "runs" / f"{_stem(dataset, year, draw)}.csv"
    frame.drop([c for c in frame.columns if c.startswith("cost_")] + ["seconds"]).write_csv(out)
    frame.write_parquet(WORK / f"{_stem(dataset, year, draw)}.parquet")
    np.savez_compressed(
        WORK / f"{_stem(dataset, year, draw)}.npz",
        names=np.array([r["policy"] for r in rows]),
        idx=keep,
        sizes=scn.sizes.astype(np.int64),
        reads=scn.window_reads()[:, scn.measure_from :].sum(axis=1).astype(np.float64),
        cost=np.array(arrays["cost"], dtype=np.float64),
        cold=np.array(arrays["cold"], dtype=np.float32),
        hours=np.array(arrays["hours"], dtype=np.float32),
        maxw=np.array(arrays["maxw"], dtype=np.float32),
    )
    return out


def run(datasets: list[str], years: list[int], draw: str, workers: int) -> None:
    jobs = [(d, y, draw) for d in datasets for y in years]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for fut in [pool.submit(run_one, *j) for j in jobs]:
            print("wrote", fut.result(), flush=True)


# ---------------------------------------------------------------------------- chooser rows


@dataclass
class Run:
    names: list[str]
    idx: IntArray
    sizes: IntArray
    reads: FloatArray
    cost: FloatArray
    cold: FloatArray
    hours: FloatArray
    maxw: FloatArray
    can_wait: npt.NDArray[np.bool_]


@cache
def load_run(dataset: str, year: int, draw: str) -> Run:
    z = np.load(WORK / f"{_stem(dataset, year, draw)}.npz")
    rows = pl.read_parquet(WORK / f"{_stem(dataset, year, draw)}.parquet")
    names = [str(n) for n in z["names"]]
    if rows["policy"].to_list() != names:
        raise ValueError("rows and arrays disagree")
    return Run(
        names,
        z["idx"],
        z["sizes"],
        z["reads"],
        z["cost"],
        z["cold"].astype(np.float64),
        z["hours"].astype(np.float64),
        z["maxw"].astype(np.float64),
        rows["can_wait"].to_numpy(),
    )


def _history(hist: Run, target: Run) -> tuple[FloatArray, FloatArray, npt.NDArray[np.bool_]]:
    """History arrays aligned on the target year's files (files without history get zeros)."""
    if hist.names != target.names:
        raise ValueError("the two runs used different grids")
    pos = np.searchsorted(target.idx, hist.idx)
    if (pos >= len(target.idx)).any() or (target.idx[pos] != hist.idx).any():
        raise ValueError("a history file is missing from the target year")
    cost = np.zeros(target.cost.shape)
    cold = np.zeros(target.cold.shape)
    has = np.zeros(len(target.idx), dtype=bool)
    cost[:, pos], cold[:, pos], has[pos] = hist.cost, hist.cold, True
    return cost, cold, has


def chooser_choices(
    dataset: str, year: int, kind: str, setting: ch.Setting, prior: IntArray | None
) -> tuple[IntArray, IntArray]:
    """(choice, prior) per file of ``year`` for the chooser (``kind`` = "chooser") or the ceiling.
    ``prior`` = last year's choice by the same setting on this year's files (default if None)."""
    target = load_run(dataset, year, "actual")
    if kind == "chooser":
        hist = load_run(dataset, year - 1, "actual")
    elif kind == "ceiling":
        hist = load_run(dataset, year, "replicate")
    else:
        raise ValueError(kind)
    cost, cold, has = _history(hist, target)
    default = target.names.index(ch.DEFAULT_POLICY)
    allowed = np.ones(len(target.names), dtype=bool)
    if setting.menu == "online":
        allowed = ~target.can_wait
    if prior is None:
        prior = np.full(len(target.idx), default, dtype=np.int64)
    switch = ch.switch_charge(PRICES[CLOUD], target.sizes)
    choice = ch.choose(cost, cold, allowed, prior, has, switch, setting)
    return choice, prior


def chooser_rows(dataset: str) -> pl.DataFrame:
    """One row per (year, family, setting): the chooser and the ceiling, scored on actual draws.

    The chooser for year Y follows its own choice for Y-1 (prior); the first year it is run
    starts from the default policy, which bills every file that leaves the default a switch."""
    years = sorted({y for pair in PAIRS for y in pair})
    rows = []
    for kind in ("chooser", "ceiling"):
        for setting in ch.SETTINGS:
            prev: tuple[IntArray, IntArray] | None = None  # (idx, choice) of the year before
            for year in years:
                target = load_run(dataset, year, "actual")
                prior = None
                if prev is not None:
                    prior = np.full(len(target.idx), target.names.index(ch.DEFAULT_POLICY))
                    pos = np.searchsorted(target.idx, prev[0])
                    prior[pos] = prev[1]
                    prior = prior.astype(np.int64)
                choice, prior_used = chooser_choices(dataset, year, kind, setting, prior)
                switch = ch.switch_charge(PRICES[CLOUD], target.sizes)
                o = ch.outcome(
                    target.cost,
                    target.cold,
                    target.hours,
                    target.maxw,
                    target.reads,
                    choice,
                    prior_used,
                    switch,
                )
                rows.append(
                    {
                        "dataset": dataset,
                        "year": year,
                        "draw": "actual",
                        "policy": f"{kind}:{setting.name}",
                        "family": kind,
                        "rival": False,
                        "cost": o.cost,
                        "reads": o.reads,
                        "cold_reads": o.cold_reads,
                        "cold_rate": o.cold_rate,
                        "wait_hours_all": o.wait_hours,
                        "wait_max_hours": o.max_wait_hours,
                        "switches": o.switches,
                        "switch_cost": o.switch_cost,
                    }
                )
                prev = (target.idx, choice)
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------- picking and verdict


def policy_rows(dataset: str, year: int) -> pl.DataFrame:
    frame = pl.read_parquet(WORK / f"{_stem(dataset, year, 'actual')}.parquet")
    return frame.select(
        "dataset",
        "year",
        "draw",
        "policy",
        "family",
        "rival",
        "cost",
        "reads",
        "cold_reads",
        "cold_rate",
        "wait_hours_all",
        "wait_max_hours",
    )


def _cheapest(frame: pl.DataFrame, cap: float) -> dict[str, Any] | None:
    ok = frame.filter(pl.col("cold_rate") <= cap + TOL).sort(["cost", "policy"])
    return ok.row(0, named=True) if ok.height else None


def _scored(frame: pl.DataFrame, policy: str) -> dict[str, Any]:
    hit = frame.filter(pl.col("policy") == policy)
    if hit.height != 1:
        raise ValueError(f"{policy}: expected one scored row, found {hit.height}")
    return hit.row(0, named=True)


def lines(table: pl.DataFrame) -> list[dict[str, Any]]:
    """Every (dataset, pair, level, rule) line of the R1 and R2 tables."""
    out = []
    for dataset in sorted(set(table["dataset"].to_list())):
        for pick_year, score_year in PAIRS:
            pick = table.filter((pl.col("dataset") == dataset) & (pl.col("year") == pick_year))
            score = table.filter((pl.col("dataset") == dataset) & (pl.col("year") == score_year))
            for level, cap in LEVELS.items():
                rival = _cheapest(pick.filter(pl.col("rival")), cap)
                if rival is None:
                    raise ValueError(f"{dataset} {pick_year} {level}: no rival meets the level")
                rival_s = _scored(score, rival["policy"])
                for rule in ("matched", "equal"):
                    limit = min(cap, rival["cold_rate"]) if rule == "matched" else cap
                    line: dict[str, Any] = {
                        "dataset": dataset,
                        "pick_year": pick_year,
                        "score_year": score_year,
                        "level": level,
                        "rule": rule,
                        "rival": rival["policy"],
                        "rival_cost": rival_s["cost"],
                        "rival_cold_rate": rival_s["cold_rate"],
                        "rival_wait_hours": rival_s["wait_hours_all"],
                        "rival_max_wait": rival_s["wait_max_hours"],
                    }
                    roles = {
                        "ours": pick.filter(pl.col("family").is_in(list(OURS))),
                        "reactive": pick.filter(pl.col("family") == "reactive"),
                        "ceiling": pick.filter(pl.col("family") == "ceiling"),
                    }
                    for role, cands in roles.items():
                        row = _cheapest(cands, limit)
                        if row is None:
                            line[f"{role}_policy"] = None
                            continue
                        s = _scored(score, row["policy"])
                        line[f"{role}_policy"] = row["policy"]
                        line[f"{role}_cost"] = s["cost"]
                        line[f"{role}_gap"] = 1.0 - s["cost"] / rival_s["cost"]
                        line[f"{role}_cold_rate"] = s["cold_rate"]
                        line[f"{role}_wait_ok"] = s["cold_rate"] <= rival_s["cold_rate"] + TOL
                        line[f"{role}_wait_hours"] = s["wait_hours_all"]
                        line[f"{role}_max_wait"] = s["wait_max_hours"]
                    if line.get("reactive_policy") and line.get("ceiling_policy"):
                        span = line["reactive_cost"] - line["ceiling_cost"]
                        if span > 0 and line.get("ours_policy"):
                            line["r2_closed"] = (line["reactive_cost"] - line["ours_cost"]) / span
                    out.append(line)
    return out


def _passes(line: dict[str, Any], role: str, gap: float) -> bool:
    return bool(
        line.get(f"{role}_policy") and line[f"{role}_gap"] >= gap and line[f"{role}_wait_ok"]
    )


def verdict(all_lines: list[dict[str, Any]]) -> dict[str, Any]:
    """R1 and R2 from the matched-rule lines (D-044); the equal-allowance lines are reported."""
    matched = [x for x in all_lines if x["rule"] == "matched"]
    datasets = sorted({x["dataset"] for x in matched})

    def holds(dataset: str, test: Any) -> bool:
        for level in LEVELS:
            pair_lines = [x for x in matched if x["dataset"] == dataset and x["level"] == level]
            if len(pair_lines) == len(PAIRS) and all(test(x) for x in pair_lines):
                return True
        return False

    c1 = {d: holds(d, lambda x: _passes(x, "ours", GAP_METHOD)) for d in datasets}
    c2 = {d: holds(d, lambda x: _passes(x, "ceiling", GAP_CEILING)) for d in datasets}
    r2 = {d: holds(d, lambda x: x.get("r2_closed", -np.inf) >= CLOSE_R2) for d in datasets}
    real = [d for d in datasets if d in REAL]
    return {
        "condition_1": {d: c1[d] for d in real},
        "condition_2": {d: c2[d] for d in real},
        "R1": sum(c1[d] for d in real) >= 2 and sum(c2[d] for d in real) >= 2,
        "R2_by_dataset": {d: r2[d] for d in real},
        "R2": sum(r2[d] for d in real) >= 2,
    }


def score(datasets: list[str]) -> dict[str, Any]:
    years = sorted({y for pair in PAIRS for y in pair})
    parts = []
    for d in datasets:
        parts.append(chooser_rows(d))
        parts += [policy_rows(d, y) for y in years]
    numeric = ["cost", "reads", "cold_reads", "cold_rate", "wait_hours_all", "wait_max_hours"]
    parts = [
        p.with_columns(
            pl.col("year").cast(pl.Int64), *[pl.col(c).cast(pl.Float64) for c in numeric]
        )
        for p in parts
    ]
    table = pl.concat(parts, how="diagonal")
    REPORTS.mkdir(parents=True, exist_ok=True)
    table.sort("dataset", "year", "family", "policy").write_csv(REPORTS / "table.csv")
    all_lines = lines(table)
    pl.DataFrame(all_lines).write_csv(REPORTS / "lines.csv")
    result = verdict(all_lines)
    result["datasets"] = datasets
    (REPORTS / "verdict.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sat.experiments.r1")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--datasets", nargs="+", default=list(REAL))
    p_run.add_argument("--years", nargs="+", type=int, required=True)
    p_run.add_argument("--draw", choices=["actual", "replicate"], default="actual")
    p_run.add_argument("--workers", type=int, default=1)
    p_score = sub.add_parser("score")
    p_score.add_argument("--datasets", nargs="+", default=list(REAL))
    args = parser.parse_args()
    if args.cmd == "run":
        run(args.datasets, args.years, args.draw, args.workers)
    else:
        print(json.dumps(score(args.datasets), indent=2))


if __name__ == "__main__":
    main()
