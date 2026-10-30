"""Gate G3, the sealed test, exactly as docs/PREREGISTRATION.md states.

Nothing here may change after the freeze tag ``freeze-g3`` is created: the sealed run unlocks 2024
and 2025 only when the code running is the tagged commit (``sat.data.sealed.unlock_sealed``).

    python -m sat.experiments.g3 run --workers 2            # unlock, simulate every scenario
    python -m sat.experiments.g3 score                      # hypotheses, reports/g3/, RESULTS.md
    python -m sat.experiments.g3 reproduce --workers 2      # H9, from a fresh clone at the tag

``--rehearsal`` runs the same code on 2020 to 2022 (data up to 2022) so the pipeline is proven
before the freeze; rehearsal results go to reports/g3-rehearsal/ and decide nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from sat.data.sealed import FREEZE_TAG, unlock_sealed
from sat.experiments import r1, zrs
from sat.experiments.e1 import REPO

FloatArray = npt.NDArray[np.float64]

SCENARIOS: dict[str, tuple[str, str]] = {  # name -> (E1 setting, price scenario)
    "base": ("central", "base"),
    "storage-x0.5": ("central", "storage-x0.5"),
    "storage-x1.5": ("central", "storage-x1.5"),
    "fees-x0.5": ("central", "fees-x0.5"),
    "fees-x1.5": ("central", "fees-x1.5"),
    "restore-low": ("restore-low", "base"),
    "reads-low": ("reads-low", "base"),
    "reads-high": ("reads-high", "base"),
    "size-low": ("size-low", "base"),
    "size-high": ("size-high", "base"),
}
SEALED = (2025, ((2023, 2024), (2024, 2025)))
REHEARSAL = (2022, ((2020, 2021), (2021, 2022)))
H1_GAP = 0.05
H2_SHARE = 0.5  # ours waits at most half as many reads as the rival
H5_SHARE = 0.8
H6_LIMIT = 0.05
CORE_HOUR_USD = 0.04  # assumed; also reported at 10 times this
BOOT = 2000
BOOT_SEED = 20261030


def study(scenario: str, rehearsal: bool) -> r1.Study:
    max_year, pairs = REHEARSAL if rehearsal else SEALED
    setting, prices = SCENARIOS[scenario]
    root = "g3-rehearsal" if rehearsal else "g3"
    return r1.Study(f"{root}/{scenario}", max_year, pairs, setting, prices)


def actual_years(st: r1.Study) -> list[int]:
    """The chooser for the first pick year needs the year before it as history."""
    return list(range(st.years[0] - 1, st.years[-1] + 1))


# ---------------------------------------------------------------------------- running


def run(scenarios: list[str], datasets: list[str], workers: int, rehearsal: bool) -> None:
    if not rehearsal:
        print("unlocked at freeze commit", unlock_sealed(REPO), flush=True)
    for name in scenarios:
        st = study(name, rehearsal)
        r1.use(st)
        r1.run(datasets, actual_years(st), "actual", workers)
        if name == "base":
            r1.run(datasets, st.years, "replicate", workers)
            jobs = [(d, y) for d in datasets for y in actual_years(st)]
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for fut in [pool.submit(zrs.run_one, *j) for j in jobs]:
                    print("wrote", fut.result(), flush=True)


# ---------------------------------------------------------------------------- scoring


def gap_interval(ours: FloatArray, rival: FloatArray) -> tuple[float, float]:
    """95% paired bootstrap interval of 1 - sum(ours) / sum(rival), resampling files."""
    rng = np.random.default_rng(BOOT_SEED)
    n, gaps = len(ours), []
    for _ in range(BOOT // 200):
        idx = rng.integers(0, n, (200, n))
        gaps.append(1.0 - ours[idx].sum(axis=1) / rival[idx].sum(axis=1))
    g = np.concatenate(gaps)
    return float(np.quantile(g, 0.025)), float(np.quantile(g, 0.975))


def _with_intervals(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for line in lines:
        if line["rule"] != "matched" or not line.get("ours_policy"):
            continue
        d, y = line["dataset"], line["score_year"]
        lo, hi = gap_interval(
            r1.per_file_cost(d, y, line["ours_policy"]), r1.per_file_cost(d, y, line["rival"])
        )
        line["ours_gap_ci_low"], line["ours_gap_ci_high"] = lo, hi
    return lines


def _naive(table: pl.DataFrame, line: dict[str, Any]) -> float | None:
    """H4: the seasonal-naive family alone, picked by the same rule as ours."""
    keys = (pl.col("dataset") == line["dataset"]) & (pl.col("family") == "seasonal")
    pick = table.filter(keys & (pl.col("year") == line["pick_year"]))
    cap = r1.LEVELS[line["level"]]
    rival_pick = table.filter(
        (pl.col("dataset") == line["dataset"])
        & (pl.col("year") == line["pick_year"])
        & (pl.col("policy") == line["rival"])
    ).row(0, named=True)
    row = r1._cheapest(pick, min(cap, rival_pick["cold_rate"]))
    if row is None:
        return None
    s = table.filter(
        keys & (pl.col("year") == line["score_year"]) & (pl.col("policy") == row["policy"])
    )
    return float(s["cost"][0])


def h1(lines: list[dict[str, Any]]) -> dict[str, bool]:
    """Per dataset: at one level, both sealed years have ours >= 5% cheaper, waiting no more
    than the rival, with the 95% interval of the gap above zero (D-046)."""
    out: dict[str, bool] = {}
    matched = [x for x in lines if x["rule"] == "matched"]
    for d in sorted({x["dataset"] for x in matched}):
        ok = False
        for level in r1.LEVELS:
            ls = [x for x in matched if x["dataset"] == d and x["level"] == level]
            ok |= len(ls) == len(r1.STUDY.pairs) and all(
                x.get("ours_policy")
                and x["ours_gap"] >= H1_GAP
                and x["ours_wait_ok"]
                and x.get("ours_gap_ci_low", -1.0) > 0
                for x in ls
            )
        out[d] = ok
    return out


def h2(lines: list[dict[str, Any]]) -> dict[str, bool]:
    """Per dataset: at L1, both sealed years have ours at no more than the rival's cost and at
    most half its share of waited reads (the rival must have waited at all)."""
    out: dict[str, bool] = {}
    matched = [x for x in lines if x["rule"] == "matched" and x["level"] == "L1"]
    for d in sorted({x["dataset"] for x in matched}):
        ls = [x for x in matched if x["dataset"] == d]
        out[d] = len(ls) == len(r1.STUDY.pairs) and all(
            x.get("ours_policy")
            and x["ours_cost"] <= x["rival_cost"]
            and x["rival_cold_rate"] > 0
            and x["ours_cold_rate"] <= H2_SHARE * x["rival_cold_rate"]
            for x in ls
        )
    return out


def _count(by_dataset: dict[str, bool]) -> bool:
    return sum(by_dataset.get(d, False) for d in r1.REAL) >= 2


def h6(lines: list[dict[str, Any]], datasets: list[str]) -> dict[str, Any]:
    """Compute for one year's choice (one grid run of the history year) against what it saves."""
    out: dict[str, Any] = {}
    for line in lines:
        if line["rule"] != "matched" or line["level"] != "L1" or not line.get("ours_policy"):
            continue
        if line["dataset"] not in datasets:
            continue
        frame = pl.read_parquet(
            r1.STUDY.work / f"{line['dataset']}_{line['score_year'] - 1}_actual.parquet"
        )
        hours = float(frame["seconds"].sum()) / 3600
        saved = line["rival_cost"] - line["ours_cost"]
        key = f"{line['dataset']}_{line['score_year']}"
        out[key] = {
            "core_hours": hours,
            "saved_usd": saved,
            "ratio": hours * CORE_HOUR_USD / saved if saved > 0 else None,
            "ratio_at_10x": hours * CORE_HOUR_USD * 10 / saved if saved > 0 else None,
        }
    return out


def score(rehearsal: bool, scenarios: list[str] | None = None) -> dict[str, Any]:
    names = scenarios or list(SCENARIOS)
    result: dict[str, Any] = {"rehearsal": rehearsal, "scenarios": {}}
    for name in names:
        st = study(name, rehearsal)
        r1.use(st)
        present = [d for d in r1.REAL if (st.work / f"{d}_{st.years[-1]}_actual.npz").exists()]
        if not present:
            continue
        table = r1.table(present, ceiling=name == "base")
        lines = _with_intervals(r1.lines(table))
        st.reports.mkdir(parents=True, exist_ok=True)
        table.sort("dataset", "year", "family", "policy").write_csv(st.reports / "table.csv")
        pl.DataFrame(lines).write_csv(st.reports / "lines.csv")
        entry: dict[str, Any] = {"datasets": present, "H1": h1(lines), "H2": h2(lines)}
        if name == "base":
            entry["H3_capture"] = {
                f"{x['dataset']}_{x['score_year']}": x["ours_gap"] / x["ceiling_gap"]
                for x in lines
                if x["rule"] == "matched"
                and x["level"] == "L1"
                and x.get("ceiling_policy")
                and x["ceiling_gap"] > 0
            }
            entry["H4_naive_gap"] = {
                f"{x['dataset']}_{x['score_year']}_{x['level']}": (
                    None if (c := _naive(table, x)) is None else 1 - x["ours_cost"] / c
                )
                for x in lines
                if x["rule"] == "matched" and x.get("ours_policy")
            }
            entry["H6"] = h6(lines, present)
            entry["azure_zrs"] = [
                {k: x.get(k) for k in ("dataset", "pick_year", "rival", "ours_policy", "ours_gap")}
                for x in zrs.score(present)
            ]
        result["scenarios"][name] = entry
    base = result["scenarios"].get("base")
    if base:
        h1_pass, h2_pass = _count(base["H1"]), _count(base["H2"])
        primary = "H1" if h1_pass else "H2" if h2_pass else None
        held = [n for n, e in result["scenarios"].items() if primary and _count(e[primary])]
        h6_ok = all(
            v["ratio"] is not None and v["ratio"] < H6_LIMIT
            for k, v in base["H6"].items()
            if primary and base[primary].get(k.split("_")[0])
        )
        result["H1"], result["H2"] = h1_pass, h2_pass
        result["H5"] = bool(primary) and len(held) >= H5_SHARE * len(SCENARIOS)
        result["H5_held_in"] = held
        result["H6"] = bool(primary) and h6_ok
        result["H7"] = True  # Gate G2, Phase 3 (docs/PHASE3_REPORT.md)
        result["H9"] = None  # set by ``reproduce``
    root = REPO / "reports" / ("g3-rehearsal" if rehearsal else "g3")
    root.mkdir(parents=True, exist_ok=True)
    (root / "results.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


# ---------------------------------------------------------------------------- H9


def reproduce(workers: int) -> bool:
    """H9: a fresh clone at the freeze tag re-simulates the base scenario from the processed data
    and scores it; every base line's cost must match this run to 3 significant figures."""
    data = REPO / "data" / "processed"
    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "clone"
        subprocess.run(
            ["git", "clone", "-q", "--branch", FREEZE_TAG, str(REPO), str(clone)], check=True
        )
        url = subprocess.run(
            ["git", "-C", str(REPO), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", url], check=True)
        env = {**os.environ, "SAT_DATA": str(data)}
        for cmd in (
            [
                "uv",
                "run",
                "python",
                "-m",
                "sat.experiments.g3",
                "run",
                "--scenarios",
                "base",
                "--workers",
                str(workers),
            ],
            ["uv", "run", "python", "-m", "sat.experiments.g3", "score", "--scenarios", "base"],
        ):
            subprocess.run(cmd, cwd=clone, env=env, check=True)
        theirs = pl.read_csv(clone / "reports" / "g3" / "base" / "lines.csv")
    ours = pl.read_csv(REPO / "reports" / "g3" / "base" / "lines.csv")
    same = True
    for col in ("rival_cost", "ours_cost"):
        a, b = ours[col].to_numpy(), theirs[col].to_numpy()
        same &= bool(np.all(np.abs(a - b) <= 5e-4 * np.maximum(np.abs(a), 1e-12)))
    path = REPO / "reports" / "g3" / "results.json"
    result = json.loads(path.read_text())
    result["H9"] = same
    path.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return same


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sat.experiments.g3")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("run", "score", "reproduce"):
        p = sub.add_parser(cmd)
        p.add_argument("--rehearsal", action="store_true")
        p.add_argument("--scenarios", nargs="+", default=list(SCENARIOS))
        p.add_argument("--datasets", nargs="+", default=list(r1.REAL))
        p.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.cmd == "run":
        run(args.scenarios, args.datasets, args.workers, args.rehearsal)
    elif args.cmd == "score":
        print(json.dumps(score(args.rehearsal, args.scenarios), indent=2, default=str))
    else:
        print("H9 reproduced:", reproduce(args.workers))


if __name__ == "__main__":
    main()
