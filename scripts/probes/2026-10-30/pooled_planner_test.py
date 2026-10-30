"""Prototype (2022 tuning data only): the same planner with a better forecast.

Replaces the planner's 'seasonal' forecast (last year's raw reads) with
    rate_i  = (reads in the last 365 days + 30 x group mean rate) / (days observed + 30)
    S       = the pool's seasonal index: pool reads in last year's same days / pool average rate
    reads   = rate_i x horizon x S
    P(read within `lead` days) = 1 - exp(-rate_i x S_lead x lead); 'near' if >= theta
Everything else (class sets, horizons, billing) is unchanged. Nothing is written into the repo.

Run from the repo: uv run python <this> DATASET CLOUD THETA [THETA ...]
"""

import csv
import sys
import time
from pathlib import Path

import numpy as np

import sat.policies.planner as PL
from sat.experiments import e1
from sat.policies import policy_grid

dataset, cloud, thetas = sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[3:]]
OUT = Path(__file__).parent / "outputs" / f"pooled_{dataset}_{cloud}.csv"
PRIOR_DAYS = 30.0
state: dict = {}


def pooled(scn, horizon: int, lead: int):  # type: ignore[no-untyped-def]
    n, D = scn.n_objects, scn.n_days
    T = scn.reads.shape[1]
    key = id(scn)
    if state.get("key") != key:
        R = scn.reads.astype(np.float64)
        cs = np.zeros((n, T + 1))
        np.cumsum(R, axis=1, out=cs[:, 1:])
        w = scn.sim_start + np.arange(D)
        lo = np.maximum(w - 365, 0)
        trailing = cs[:, w] - cs[:, lo]
        exposure = np.clip(w[None, :] - np.maximum(scn.created[:, None], lo[None, :]), 1, 365).astype(np.float64)
        gi = state["gi"]
        rate = np.zeros((n, D))
        pcs_list = []
        for g in range(gi.max() + 1):
            m = gi == g
            mean_rate = trailing[m].sum(axis=0) / np.maximum(exposure[m].sum(axis=0), 1.0)  # (D,)
            rate[m] = (trailing[m] + PRIOR_DAYS * mean_rate[None, :]) / (exposure[m] + PRIOR_DAYS)
            pcs = np.zeros(T + 1)
            np.cumsum(R[m].sum(axis=0), out=pcs[1:])
            pcs_list.append(pcs)
        state.update(key=key, rate=rate, pcs=pcs_list, w=w, T=T)
    rate, pcs_list, w, T = state["rate"], state["pcs"], state["w"], state["T"]

    def s_index(h: int):  # type: ignore[no-untyped-def]
        out = np.ones((len(pcs_list), D))
        for g, pcs in enumerate(pcs_list):
            a = np.clip(w - 364, 0, T)
            b = np.clip(w - 364 + h, 0, T)
            c = np.clip(w - 364 - 365, 0, T)
            last = pcs[b] - pcs[a]
            base = (pcs[a] - pcs[c]) * h / 365.0
            out[g] = np.where(base > 0, np.clip(last / np.where(base > 0, base, 1.0), 0.2, 5.0), 1.0)
        return out[state["gi"]]

    s_h, s_l = s_index(horizon), s_index(lead)
    reads_h = rate * horizon * s_h
    read_days = horizon * (1.0 - np.exp(-reads_h / horizon))
    near = (1.0 - np.exp(-rate * s_l * lead)) >= state["theta"]
    return reads_h, read_days, near


orig = PL._forecast


def patched(scn, kind, horizon, lead):  # type: ignore[no-untyped-def]
    if kind == "seasonal":
        return pooled(scn, horizon, lead)
    return orig(scn, kind, horizon, lead)


PL._forecast = patched

objs = e1.load_objects(dataset, 2022, "central")
scn, keep = e1.scenario(objs, cloud, "tune", "central")
if "cohort_A" in objs.groups:
    gi = np.where(objs.groups["cohort_A"][keep], 0, 1)
else:
    gi = np.zeros(scn.n_objects, dtype=int)
state["gi"] = gi
pols = [p for p in policy_grid(cloud) if p.name.startswith("seasonal-planner:")]
print(dataset, cloud, len(pols), "planner settings x", thetas, flush=True)
rows = []
for th in thetas:
    state["theta"] = th
    state["key"] = None
    for pol in pols:
        t0 = time.time()
        res = pol.run(scn)
        r = e1._row(pol, scn, res, time.time() - t0)
        r["theta"] = th
        rows.append(r)
    best = min((r for r in rows if r["theta"] == th and r["cold_rate"] <= 1e-12), key=lambda r: r["cost"], default=None)
    best1 = min((r for r in rows if r["theta"] == th and r["cold_rate"] <= 0.01), key=lambda r: r["cost"], default=None)
    print("theta", th, "best L0", best and round(best["cost"], 3), "best L1", best1 and round(best1["cost"], 3), flush=True)
with OUT.open("w", newline="") as f:
    w_ = csv.DictWriter(f, fieldnames=list(rows[0]))
    w_.writeheader()
    w_.writerows(rows)
print("wrote", OUT)
