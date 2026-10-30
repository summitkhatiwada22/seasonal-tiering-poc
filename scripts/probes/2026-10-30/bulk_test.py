"""Quick test (2022 tuning data only): what if forecast-driven restores use AWS *bulk* speed?

Run from the repo:  uv run python <this file> {std|bulk} {D1|D3|D4|D7} [limit]
Reads only data up to 2022 (period 'tune'). Writes a CSV to outputs/ next to this file.
"""

import csv
import dataclasses
import sys
import time
from pathlib import Path

import sat.policies.planner as PL
import sat.policies.policies as P
from sat.experiments import e1
from sat.policies import policy_grid
from sat.sim import SimConfig

mode, dataset = sys.argv[1], sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
OUT = Path(__file__).parent / "outputs" / f"bulk_{mode}_{dataset}.csv"

if mode == "bulk":

    def bulk_cfg(scn, keep_days=1):  # type: ignore[no-untyped-def]
        return SimConfig(
            restore_time=scn.restore_time,
            measure_from=scn.measure_from,
            on_demand_keep_days=keep_days,
            up_move_speed="bulk",
        )

    P._sim_config = bulk_cfg
    PL._sim_config = bulk_cfg
    RealRestore = P.Restore
    P.Restore = lambda obj, day, keep: RealRestore(obj, day, keep, "bulk")  # type: ignore[assignment]
    orig_rules_for = PL.rules_for

    def bulk_rules(sheet):  # type: ignore[no-untyped-def]
        r = orig_rules_for(sheet)
        return dataclasses.replace(
            r,
            restore_fee_by_speed={**r.restore_fee_by_speed, "standard": r.restore_fee_by_speed["bulk"]},
            retrieval_by_speed={**r.retrieval_by_speed, "standard": r.retrieval_by_speed["bulk"]},
        )

    PL.rules_for = bulk_rules


def wanted(p):  # type: ignore[no-untyped-def]
    if p.family not in ("seasonal", "oracle", "reactive"):
        return False
    return "glacier_flexible" in p.name or "deep_archive" in p.name


objs = e1.load_objects(dataset, 2022, "central")
scn, keep = e1.scenario(objs, "aws", "tune", "central")
pols = [p for p in policy_grid("aws") if wanted(p)]
if limit:
    pols = pols[:limit]
print(mode, dataset, len(pols), "policies", flush=True)
rows = []
for i, pol in enumerate(pols):
    t0 = time.time()
    res = pol.run(scn)
    rows.append(e1._row(pol, scn, res, time.time() - t0))
    print(i, pol.name, round(rows[-1]["cost"], 4), round(rows[-1]["cold_rate"], 4), round(time.time() - t0, 1), flush=True)
with OUT.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print("wrote", OUT)
