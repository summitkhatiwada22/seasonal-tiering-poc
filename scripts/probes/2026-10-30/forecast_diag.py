"""Diagnostic (data up to 2022 only): how good are simple forecasts of the next 30 days of reads?

Origins: the 1st of each month of 2022. Each forecast uses reads strictly before the origin.
Methods: naive364 (same days last year), recent30, year-rate (trailing 365 d), pooled-seasonal
(year-rate x a seasonal index from the pool), shrunk-pooled (Gamma-Poisson shrinkage of the year
rate, then x the seasonal index). Truth: the realised reads and the noise-free expected reads.
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from sat.data.mapping import READ_SEED, default_scales, to_reads
from sat.experiments import e1

OUT = Path(__file__).parent / "outputs" / "forecast_diag.json"
H = 30
LAG = 364


def auc(score: np.ndarray, label: np.ndarray) -> float:
    pos, neg = label.sum(), (~label).sum()
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    # average ranks for ties
    s = score[order]
    i = 0
    r = np.empty(len(score))
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        r[i : j + 1] = (i + j) / 2 + 1
        i = j + 1
    ranks[order] = r
    return float((ranks[label].sum() - pos * (pos + 1) / 2) / (pos * neg))


def eb_gamma(n: np.ndarray) -> tuple[float, float]:
    m, v = float(n.mean()), float(n.var())
    if v <= m or m <= 0:
        return 1e6, 1e6 / max(m, 1e-9)
    beta = m / (v - m)
    return m * beta, beta


def run(ds: str) -> dict:
    demand = e1._demand(ds, 2022)
    scale = default_scales(demand, "central")
    reads = to_reads(demand, scale, "central", seed=READ_SEED).astype(np.float64)
    expected = scale[:, None] * demand.counts
    created = demand.first_demand_day()
    groups = (
        [demand.groups["cohort_A"], demand.groups["cohort_B"]]
        if ds == "D1"
        else [np.ones(len(demand.names), bool)]
    )
    csum = np.concatenate([np.zeros((reads.shape[0], 1)), np.cumsum(reads, axis=1)], axis=1)

    def win(a: int, b: int) -> np.ndarray:  # reads in [a, b)
        return csum[:, b] - csum[:, a]

    ecs = np.concatenate([np.zeros((reads.shape[0], 1)), np.cumsum(expected, axis=1)], axis=1)

    def ewin(a: int, b: int) -> np.ndarray:  # noise-free expected reads in [a, b)
        return ecs[:, b] - ecs[:, a]

    acc: dict[str, dict[str, list]] = {}
    methods = ["naive364", "recent30", "year_rate", "pooled_seasonal", "shrunk_pooled", "naive364_denoised", "year_rate_denoised"]
    for m in range(1, 13):
        t = demand.day_index(date(2022, m, 1))
        live = created < t - 365  # objects with a full trailing year of existence
        if live.sum() < 50:
            continue
        actual = win(t, t + H)
        truth = expected[:, t : t + H].sum(axis=1)
        trailing = win(t - 365, t)
        f = {
            "naive364": win(t - LAG, t - LAG + H),
            "recent30": win(t - 30, t),
            "year_rate": trailing * H / 365.0,
            "naive364_denoised": ewin(t - LAG, t - LAG + H),
            "year_rate_denoised": ewin(t - 365, t) * H / 365.0,
        }
        f_pool = np.zeros_like(trailing)
        f_shr = np.zeros_like(trailing)
        for g in groups:
            gm = g & live
            if gm.sum() < 20:
                continue
            # seasonal index of the pool: last year's same window vs that year's average rate
            last = win(t - LAG, t - LAG + H)[gm].sum()
            base = win(t - LAG - 365, t - LAG)[gm].sum() * H / 365.0
            s_idx = last / base if base > 0 else 1.0
            f_pool[gm] = trailing[gm] * H / 365.0 * s_idx
            a, b = eb_gamma(trailing[gm])
            post = (a + trailing[gm]) / (b + 1.0)  # posterior mean reads per trailing year
            f_shr[gm] = post * H / 365.0 * s_idx
        f["pooled_seasonal"], f["shrunk_pooled"] = f_pool, f_shr
        for name in methods:
            fm = f[name][live]
            d = acc.setdefault(name, {"abs_act": [], "abs_truth": [], "auc": []})
            d["abs_act"].append((np.abs(fm - actual[live]).sum(), actual[live].sum()))
            d["abs_truth"].append((np.abs(fm - truth[live]).sum(), truth[live].sum()))
            d["auc"].append(auc(fm, actual[live] > 0))
        floor = acc.setdefault("noise_floor", {"abs_act": [], "abs_truth": [], "auc": []})
        floor["abs_act"].append((np.abs(truth[live] - actual[live]).sum(), actual[live].sum()))
        floor["abs_truth"].append((0.0, truth[live].sum()))
        floor["auc"].append(auc(truth[live], actual[live] > 0))
    out = {}
    for name, d in acc.items():
        out[name] = {
            "wape_vs_actual": sum(a for a, _ in d["abs_act"]) / sum(b for _, b in d["abs_act"]),
            "wape_vs_truth": sum(a for a, _ in d["abs_truth"]) / sum(b for _, b in d["abs_truth"]),
            "auc_any_read": float(np.nanmean(d["auc"])),
        }
    # seasonal strength of the pooled truth demand and object-level profile stability
    yrs = range(2017, 2023)
    prof = []
    for y in yrs:
        a, b = demand.day_index(date(y, 1, 1)), demand.day_index(date(y + 1, 1, 1))
        months = np.array(
            [
                expected[:, demand.day_index(date(y, mo, 1)) : demand.day_index(date(y + (mo == 12), mo % 12 + 1, 1))].sum()
                for mo in range(1, 13)
            ]
        )
        prof.append(months / months.mean())
    prof = np.array(prof)
    mean_prof = prof.mean(axis=0)
    def monthly(y: int) -> np.ndarray:
        cols = []
        for mo in range(1, 13):
            a = demand.day_index(date(y, mo, 1))
            b = demand.day_index(date(y + (mo == 12), mo % 12 + 1, 1))
            cols.append(expected[:, a:b].sum(axis=1))
        return np.array(cols).T

    m1, m2 = monthly(2021), monthly(2022)
    ok = (m1.sum(axis=1) > 0) & (m2.sum(axis=1) > 0) & (created < demand.day_index(date(2021, 1, 1)))
    x1 = m1[ok] / m1[ok].mean(axis=1, keepdims=True)
    x2 = m2[ok] / m2[ok].mean(axis=1, keepdims=True)
    x1c, x2c = x1 - x1.mean(axis=1, keepdims=True), x2 - x2.mean(axis=1, keepdims=True)
    den = np.sqrt((x1c**2).sum(axis=1) * (x2c**2).sum(axis=1))
    corr = np.where(den > 0, (x1c * x2c).sum(axis=1) / np.where(den > 0, den, 1), np.nan)
    out["object_profile_corr_2021_vs_2022_pctiles_10_25_50_75_90"] = [
        float(v) for v in np.nanpercentile(corr, [10, 25, 50, 75, 90])
    ]
    out["share_objects_profile_corr_above_0.5"] = float(np.nanmean(corr > 0.5))
    out["pooled_truth_seasonal_strength"] = float(
        mean_prof.var() / (mean_prof.var() + ((prof - mean_prof) ** 2).mean())
    )
    out["pooled_truth_peak_to_trough"] = float(mean_prof.max() / mean_prof.min())
    out["n_objects_live_at_dec"] = int((created < demand.day_index(date(2021, 12, 1))).sum())
    return out


if __name__ == "__main__":
    res = {}
    for ds in sys.argv[1:] or ["D1", "D3", "D4"]:
        res[ds] = run(ds)
        print(ds, json.dumps(res[ds], indent=1), flush=True)
    OUT.write_text(json.dumps(res, indent=1))
