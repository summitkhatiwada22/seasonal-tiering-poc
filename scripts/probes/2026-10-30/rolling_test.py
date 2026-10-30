"""Out-of-sample check on already-used years: pick settings on 2021, score them on 2022.

Runs the AWS policy grid with data up to 2021 only (simulate 2020-2021, measure 2021).
mode std = policies as in Phase 4 (whole grid); mode bulk = restores at AWS bulk speed, only for the
policies that restore from Glacier Flexible or Deep Archive (the others are unchanged by bulk).
Usage: uv run python rolling_test.py {std|bulk} DATASET     (writes a CSV next to this file)
"""
import csv, dataclasses, sys, time
from datetime import date
from pathlib import Path
import sat.policies.planner as PL
import sat.policies.policies as P
from sat.experiments import e1
from sat.policies import policy_grid
from sat.sim import SimConfig

mode, dataset = sys.argv[1], sys.argv[2]
OUT = Path(__file__).parent / "outputs" / f"roll21_{mode}_{dataset}.csv"
e1.PERIODS["tune21"] = (2021, date(2020, 1, 1), date(2021, 1, 1))
if mode == "bulk":
    def bulk_cfg(scn, keep_days=1):
        return SimConfig(restore_time=scn.restore_time, measure_from=scn.measure_from,
                         on_demand_keep_days=keep_days, up_move_speed="bulk")
    P._sim_config = bulk_cfg; PL._sim_config = bulk_cfg
    RealRestore = P.Restore
    P.Restore = lambda obj, day, keep: RealRestore(obj, day, keep, "bulk")
    orig_rules_for = PL.rules_for
    def bulk_rules(sheet):
        r = orig_rules_for(sheet)
        return dataclasses.replace(r,
            restore_fee_by_speed={**r.restore_fee_by_speed, "standard": r.restore_fee_by_speed["bulk"]},
            retrieval_by_speed={**r.retrieval_by_speed, "standard": r.retrieval_by_speed["bulk"]})
    PL.rules_for = bulk_rules

def wanted(p):
    if mode == "std":
        return True
    return p.family in ("seasonal", "oracle", "reactive") and ("glacier_flexible" in p.name or "deep_archive" in p.name)

objs = e1.load_objects(dataset, 2021, "central")
scn, keep = e1.scenario(objs, "aws", "tune21", "central")
pols = [p for p in policy_grid("aws") if wanted(p)]
print(mode, dataset, len(pols), "policies; objects", scn.n_objects, flush=True)
rows = []
for i, pol in enumerate(pols):
    t0 = time.time()
    res = pol.run(scn)
    rows.append(e1._row(pol, scn, res, time.time() - t0))
    if i % 10 == 0: print(i, pol.name, round(rows[-1]["cost"], 3), flush=True)
with OUT.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("wrote", OUT)
