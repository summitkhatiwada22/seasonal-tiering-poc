"""Forecastable ceiling (2022 tuning data only): the same planner told each file's TRUE EXPECTED reads
(scale x demand) but not the random draw. Nothing is written into the repo.

Original prototype notes:

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
OUT = Path(__file__).parent / "outputs" / f"rateoracle_{dataset}_{cloud}.csv"
PRIOR_DAYS = 30.0
state: dict = {}


def pooled(scn, horizon: int, lead: int):  # type: ignore[no-untyped-def]
    n, D = scn.n_objects, scn.n_days
    E = state["E"]  # (n, T) expected reads per day, aligned with scn.reads
    T = E.shape[1]
    key = id(scn)
    if state.get("key") != key:
        cs = np.zeros((n, T + 1)); np.cumsum(E, axis=1, out=cs[:, 1:])
        ds = np.zeros((n, T + 1)); np.cumsum(1.0 - np.exp(-E), axis=1, out=ds[:, 1:])
        state.update(key=key, cs=cs, ds=ds, w=scn.sim_start + np.arange(D))
    cs, ds, w = state["cs"], state["ds"], state["w"]
    hi = np.minimum(w + horizon, T)
    reads_h = cs[:, hi] - cs[:, w]
    read_days = ds[:, hi] - ds[:, w]
    lo_ = np.minimum(w + lead, T)
    near = (1.0 - np.exp(-(cs[:, lo_] - cs[:, w]))) >= state["theta"]
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
from sat.data.mapping import default_scales
dem = e1._demand(dataset, 2022)
E_all = default_scales(dem, "central")[:, None] * dem.counts
state["E"] = E_all[keep]
assert state["E"].shape == scn.reads.shape, (state["E"].shape, scn.reads.shape)
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
