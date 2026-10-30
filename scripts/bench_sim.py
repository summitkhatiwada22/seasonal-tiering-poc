"""Speed check at full real-data size: 10,000 objects x 3,653 days (10 years), random plans.

Run: ``uv run python scripts/bench_sim.py``. Random inputs, not results.
"""

import time
from datetime import date
from pathlib import Path

import numpy as np

from sat.prices import load_all
from sat.sim import (
    Inventory,
    ITConfig,
    Plan,
    Restore,
    simulate,
    simulate_autoclass,
    simulate_intelligent_tiering,
)

P = load_all(Path("configs/prices"))
n, days = 10_000, 3653
rng = np.random.default_rng(0)
sizes = rng.lognormal(np.log(60_000), 2.0, n).astype(np.int64) + 1
reads = rng.poisson(0.02, (n, days)).astype(np.int32)
for cloud in ("aws", "gcs", "azure"):
    s = P[cloud]
    t_count = len(s.tier_order)
    tier = np.repeat(rng.integers(0, t_count, (n, 10)), days // 10 + 1, axis=1)[:, :days]
    archive = [i for i, t in enumerate(s.tier_order) if s.get(t, "restore_hours") > 0]
    restores = []
    if archive:
        ii, dd = np.nonzero(np.isin(tier, archive) & (np.arange(days) % 365 == 100))
        restores = [Restore(int(i), int(d), 14) for i, d in zip(ii, dd, strict=True)]
    t0 = time.time()
    r = simulate(s, Inventory(sizes), reads, Plan(tier=tier, restores=restores), date(2016, 1, 1))
    print(f"{cloud}: {time.time() - t0:.1f}s, {len(restores)} planned restores")
t0 = time.time()
simulate_intelligent_tiering(P["aws"], Inventory(sizes), reads, date(2016, 1, 1), ITConfig(90, 180))
print(f"Intelligent-Tiering: {time.time() - t0:.1f}s")
t0 = time.time()
simulate_autoclass(P["gcs"], Inventory(sizes), reads, date(2016, 1, 1), "archive")
print(f"Autoclass: {time.time() - t0:.1f}s")
