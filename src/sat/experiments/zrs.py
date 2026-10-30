"""Azure on the zone-redundant sheet, with smart tier as the rival (round two, D-049).

Reported next to gate R1, never part of it (docs/R1_PROTOCOL.md, addendum A). Same years, draws,
pick rule and waiting rules as R1. The ZRS sheet has no archive tier, so no read ever waits and the
two levels give the same picks. Ours = the seasonal policies and the per-file chooser (menu of
every policy, default smart tier). The forecastable ceiling is not run for Azure.

    python -m sat.experiments.zrs run --datasets D1 D3 D4 --years 2019 2020 2021 2022
    python -m sat.experiments.zrs score
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from typing import Any

import numpy as np
import polars as pl

from sat.experiments import chooser as ch
from sat.experiments import r1
from sat.experiments.e1 import REPO, _row
from sat.policies import Scenario
from sat.policies.grid import zrs_grid
from sat.prices import PriceSheet, load_all

SHEET: PriceSheet = load_all(REPO / "configs" / "prices" / "azure_zrs")["azure"]
DEFAULT = "smart-tier"
SETTINGS = tuple(ch.Setting("all", 0.0, m) for m in ch.MARGINS)


def scenario(dataset: str, year: int) -> tuple[Scenario, np.ndarray]:
    aws, keep = r1.scenario(dataset, year, "actual")
    return (
        Scenario(
            aws.dataset,
            SHEET,
            aws.sizes,
            aws.reads,
            aws.created,
            aws.hist_start,
            aws.sim_start,
            aws.n_days,
            aws.measure_from,
        ),
        keep,
    )


def _stem(dataset: str, year: int) -> str:
    return f"zrs_{dataset}_{year}_actual"


def run_one(dataset: str, year: int) -> str:
    scn, keep = scenario(dataset, year)
    rows, cost = [], []
    for pol in zrs_grid():
        t0 = time.time()
        res = pol.run(scn)
        rows.append(_row(pol, scn, res, time.time() - t0))
        if res.per_object_measured is None:
            raise ValueError(f"{pol.name}: no per-file cost")
        cost.append(res.per_object_measured)
    (r1.STUDY.reports / "zrs" / "runs").mkdir(parents=True, exist_ok=True)
    r1.STUDY.work.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame(rows).with_columns(
        pl.lit(dataset).alias("dataset"), pl.lit(year).alias("year"), pl.lit("actual").alias("draw")
    )
    frame.drop([c for c in frame.columns if c.startswith("cost_")] + ["seconds"]).write_csv(
        r1.STUDY.reports / "zrs" / "runs" / f"{_stem(dataset, year)}.csv"
    )
    frame.write_parquet(r1.STUDY.work / f"{_stem(dataset, year)}.parquet")
    np.savez_compressed(
        r1.STUDY.work / f"{_stem(dataset, year)}.npz",
        names=np.array([r["policy"] for r in rows]),
        idx=keep,
        sizes=scn.sizes,
        cost=np.array(cost, dtype=np.float64),
    )
    return _stem(dataset, year)


def _load(dataset: str, year: int) -> dict[str, Any]:
    return _load_at(r1.STUDY.work, dataset, year)


@cache
def _load_at(work: Any, dataset: str, year: int) -> dict[str, Any]:
    z = np.load(work / f"{_stem(dataset, year)}.npz")
    return {k: z[k] for k in z.files}


def chooser_rows(dataset: str) -> pl.DataFrame:
    years = r1.STUDY.years
    rows = []
    for setting in SETTINGS:
        prev: tuple[np.ndarray, np.ndarray] | None = None
        for year in years:
            target, hist = _load(dataset, year), _load(dataset, year - 1)
            names = [str(n) for n in target["names"]]
            n_pol, n = target["cost"].shape
            default = names.index(DEFAULT)
            pos = np.searchsorted(target["idx"], hist["idx"])
            cost = np.zeros((n_pol, n))
            has = np.zeros(n, dtype=bool)
            cost[:, pos], has[pos] = hist["cost"], True
            prior = np.full(n, default, dtype=np.int64)
            if prev is not None:
                prior[np.searchsorted(target["idx"], prev[0])] = prev[1]
            switch = ch.switch_charge(SHEET, target["sizes"])
            zeros = np.zeros((n_pol, n))
            choice = ch.choose(cost, zeros, np.ones(n_pol, dtype=bool), prior, has, switch, setting)
            o = ch.outcome(target["cost"], zeros, zeros, zeros, np.ones(n), choice, prior, switch)
            rows.append(
                {
                    "dataset": dataset,
                    "year": year,
                    "draw": "actual",
                    "policy": f"chooser:{setting.name}",
                    "family": "chooser",
                    "rival": False,
                    "cost": o.cost,
                    "reads": 0.0,
                    "cold_reads": 0.0,
                    "cold_rate": 0.0,
                    "wait_hours_all": 0.0,
                    "wait_max_hours": 0.0,
                    "switches": o.switches,
                    "switch_cost": o.switch_cost,
                }
            )
            prev = (target["idx"], choice)
    return pl.DataFrame(rows)


def score(datasets: list[str]) -> list[dict[str, Any]]:
    years = r1.STUDY.years
    numeric = ["cost", "reads", "cold_reads", "cold_rate", "wait_hours_all", "wait_max_hours"]
    parts = [chooser_rows(d) for d in datasets]
    for d in datasets:
        for y in years:
            frame = pl.read_parquet(r1.STUDY.work / f"{_stem(d, y)}.parquet")
            parts.append(
                frame.select("dataset", "year", "draw", "policy", "family", "rival", *numeric)
            )
    parts = [
        p.with_columns(
            pl.col("year").cast(pl.Int64), *[pl.col(c).cast(pl.Float64) for c in numeric]
        )
        for p in parts
    ]
    table = pl.concat(parts, how="diagonal")
    (r1.STUDY.reports / "zrs").mkdir(parents=True, exist_ok=True)
    table.sort("dataset", "year", "family", "policy").write_csv(
        r1.STUDY.reports / "zrs" / "table.csv"
    )
    lines = [x for x in r1.lines(table) if x["rule"] == "matched" and x["level"] == "L0"]
    pl.DataFrame(lines).write_csv(r1.STUDY.reports / "zrs" / "lines.csv")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sat.experiments.zrs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--datasets", nargs="+", default=list(r1.REAL))
    p_run.add_argument("--years", nargs="+", type=int, required=True)
    p_run.add_argument("--workers", type=int, default=1)
    p_score = sub.add_parser("score")
    p_score.add_argument("--datasets", nargs="+", default=list(r1.REAL))
    args = parser.parse_args()
    if args.cmd == "run":
        jobs = [(d, y) for d in args.datasets for y in args.years]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for fut in [pool.submit(run_one, *j) for j in jobs]:
                print("wrote", fut.result(), flush=True)
    else:
        for line in score(args.datasets):
            print(
                json.dumps(
                    {
                        k: line.get(k)
                        for k in ("dataset", "pick_year", "rival", "ours_policy", "ours_gap")
                    }
                )
            )


if __name__ == "__main__":
    main()
