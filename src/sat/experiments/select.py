"""Selection on 2022 and the E1 verdict on 2023, exactly as docs/E1_PROTOCOL.md states."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from sat.experiments.e1 import LEVELS, PICKS_FROM, REAL, REPO, REPORTS, results

GAP_TO_PASS = 0.05
TOL = 1e-12


def _cheapest(frame: pl.DataFrame, cap: float) -> dict[str, Any] | None:
    ok = frame.filter(pl.col("cold_rate") <= cap + TOL).sort(["cost", "policy"])
    return ok.row(0, named=True) if ok.height else None


def pick(tune: pl.DataFrame) -> list[dict[str, Any]]:
    """For each dataset, cloud and level: the cheapest rival meeting the level, then the cheapest
    seasonal (and reactive) configuration whose 2022 cold-read rate is no higher than that
    rival's."""
    picks = []
    for (dataset, cloud), part in tune.group_by("dataset", "cloud", maintain_order=True):
        for level, cap in LEVELS.items():
            rival = _cheapest(part.filter(pl.col("rival")), cap)
            if rival is None:
                raise ValueError(f"{dataset}/{cloud}/{level}: no rival meets the level")
            limit = min(cap, rival["cold_rate"])
            for role in ("rival", "seasonal", "reactive"):
                row: dict[str, Any] | None = rival
                if role != "rival":
                    row = _cheapest(part.filter(pl.col("family") == role), limit)
                if row is None:
                    continue
                picks.append(
                    {
                        "dataset": dataset,
                        "cloud": cloud,
                        "level": level,
                        "role": role,
                        "policy": row["policy"],
                        "tune_cost": row["cost"],
                        "tune_cold_rate": row["cold_rate"],
                    }
                )
    return picks


def write_picks(setting: str) -> Path:
    tune = results(setting, "tune")
    out = REPORTS / setting / "picks.json"
    payload = {
        "setting": setting,
        "rule": "docs/E1_PROTOCOL.md section 4",
        "picks": pick(tune),
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


# ---------------------------------------------------------------------------- hindsight bound


def hindsight(cost: np.ndarray, cold: np.ndarray, reads: np.ndarray, max_cold: float) -> float:
    """Lowest total cost found by choosing, object by object and knowing the future, one of the
    plans that were run, with at most ``max_cold`` reads waiting in total.

    Start from each object's cheapest plan with no waiting read (always exists: the first class),
    then add the cheapest-per-waiting-read switches greedily while the budget lasts. Greedy gives a
    feasible choice, so the result is an upper estimate of the true best (a conservative bound)."""
    big = np.where(cold > 0, np.inf, cost)
    base_idx = big.argmin(axis=0)
    cols = np.arange(cost.shape[1])
    base = cost[base_idx, cols]
    total = float(base.sum())
    if max_cold <= 0:
        return total
    saving = base[None, :] - cost
    ratio = np.where((cold > 0) & (saving > 0), saving / np.maximum(cold, 1e-300), -np.inf)
    best = ratio.argmax(axis=0)
    best_ratio = ratio[best, cols]
    order = np.argsort(-best_ratio)
    budget = max_cold
    for i in order:
        if not np.isfinite(best_ratio[i]):
            break
        c = cold[best[i], i]
        if c <= budget:
            budget -= c
            total -= saving[best[i], i]
    return total


# ---------------------------------------------------------------------------- verdict


def _npz(setting: str, dataset: str, cloud: str) -> dict[str, np.ndarray]:
    path = REPO / "data" / "e1" / setting / "eval" / f"{dataset}_{cloud}.npz"
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def verdict(setting: str) -> dict[str, Any]:
    picks_setting = PICKS_FROM.get(setting, setting)
    picks = json.loads((REPORTS / picks_setting / "picks.json").read_text())["picks"]
    ev = results(setting, "eval")
    lines = []
    for (dataset, cloud, level), group in _group(picks).items():
        part = ev.filter((pl.col("dataset") == dataset) & (pl.col("cloud") == cloud))
        by_name = {r["policy"]: r for r in part.iter_rows(named=True)}
        rival = by_name[group["rival"]["policy"]]
        line: dict[str, Any] = {
            "dataset": dataset,
            "cloud": cloud,
            "level": level,
            "rival": rival["policy"],
            "rival_cost": rival["cost"],
            "rival_cold_rate": rival["cold_rate"],
        }
        for role in ("seasonal", "reactive"):
            if role not in group:
                continue
            row = by_name[group[role]["policy"]]
            line[role] = row["policy"]
            line[f"{role}_cost"] = row["cost"]
            line[f"{role}_cold_rate"] = row["cold_rate"]
            line[f"{role}_gap"] = 1 - row["cost"] / rival["cost"]
            line[f"{role}_wait_ok"] = row["cold_rate"] <= rival["cold_rate"] + TOL
        line["passes"] = bool(
            "seasonal" in group and line["seasonal_gap"] >= GAP_TO_PASS and line["seasonal_wait_ok"]
        )
        if "seasonal" in group and "reactive" in group:
            line["seasonal_vs_reactive"] = 1 - line["seasonal_cost"] / line["reactive_cost"]
        if setting not in PICKS_FROM:
            arrays = _npz(setting, dataset, cloud)
            reads = arrays["reads"]
            max_cold = min(LEVELS[level], rival["cold_rate"]) * float(reads.sum())
            bound = hindsight(arrays["cost"], arrays["cold"], reads, max_cold)
            line["hindsight_cost"] = bound
            line["hindsight_gap"] = 1 - bound / rival["cost"]
            oracle = part.filter(
                (pl.col("family") == "oracle") & (pl.col("cold_rate") <= rival["cold_rate"] + TOL)
            ).sort("cost")
            if oracle.height:
                line["perfect_forecast_best"] = oracle["policy"][0]
                line["perfect_forecast_gap"] = 1 - oracle["cost"][0] / rival["cost"]
            line["groups"] = _groups(arrays, group, line)
        lines.append(line)
    real = [x for x in lines if x["dataset"] in REAL]
    passing = sorted({x["dataset"] for x in real if x["passes"]})
    any_bound = any(x.get("hindsight_gap", 0) >= GAP_TO_PASS for x in real)
    out = {
        "setting": setting,
        "picks_from": picks_setting,
        "rule": "docs/E1_PROTOCOL.md section 5",
        "real_datasets_passing": passing,
        "decision": "CONTINUE" if passing else "STOP AND RETHINK",
        "hindsight_bound_reaches_5pct_somewhere": any_bound if setting not in PICKS_FROM else None,
        "lines": lines,
    }
    (REPORTS / setting / "verdict.json").write_text(json.dumps(out, indent=2, default=float))
    return out


def _group(picks: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for p in picks:
        out.setdefault((p["dataset"], p["cloud"], p["level"]), {})[p["role"]] = p
    return out


def _groups(
    arrays: dict[str, np.ndarray], group: dict[str, Any], line: dict[str, Any]
) -> dict[str, dict[str, float]]:
    """Gap of the picked seasonal policy against the picked rival inside each object group."""
    names = list(arrays["names"])
    masks = {k[len("group_") :]: v for k, v in arrays.items() if k.startswith("group_")}
    if "flagged" in masks:
        masks["unflagged"] = ~masks["flagged"]
    out: dict[str, dict[str, float]] = {}
    if "seasonal" not in group:
        return out
    r = names.index(line["rival"])
    s = names.index(line["seasonal"])
    reads = arrays["reads"]
    for name, mask in masks.items():
        if not mask.any():
            continue
        rc, sc = arrays["cost"][r, mask].sum(), arrays["cost"][s, mask].sum()
        total_reads = reads[mask].sum()
        out[name] = {
            "objects": int(mask.sum()),
            "rival_cost": float(rc),
            "seasonal_cost": float(sc),
            "gap": float(1 - sc / rc) if rc else 0.0,
            "rival_cold_rate": float(arrays["cold"][r, mask].sum() / total_reads)
            if total_reads
            else 0.0,
            "seasonal_cold_rate": float(arrays["cold"][s, mask].sum() / total_reads)
            if total_reads
            else 0.0,
        }
    return out
