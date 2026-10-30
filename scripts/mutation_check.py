# ruff: noqa: E501
"""Check of the checks: plant one deliberate bug at a time in the simulator (Gate G2) and in the Phase 4
data, policy and E1 code, and confirm the tests fail. Every planted bug must be caught. Run: ``uv run python scripts/mutation_check.py``.

The source file is always restored, even if a test run crashes, and no compiled cache is kept.
"""

import os
import pathlib
import shutil
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
M = [
    (
        "sim/engine.py",
        "np.ceil((ready + 24.0 * keep) / 24.0 - 1e-9) * 24.0",
        "(ready + 24.0 * keep)",
        "copy expiry not rounded to midnight",
    ),
    (
        "sim/engine.py",
        "remaining * self.price[src] * self.early_gb[src, ids] * leave_factor",
        "remaining * self.price[src] * self.early_gb[src, ids] / 30",
        "early deletion always /30",
    ),
    (
        "sim/engine.py",
        "keeps_clock = down and self.rules.lifecycle_keeps_clock",
        "keeps_clock = False",
        "Google lifecycle resets clock",
    ),
    (
        "sim/engine.py",
        'fee = self.up_fee[dst] if self.rules.up_fee_on == "dest" else self.up_fee[src]',
        "fee = self.up_fee[dst]",
        "Azure up-move fee on destination",
    ),
    (
        "sim/engine.py",
        'self.ledger.charge("retrieval", day, ids, self.size_gb[ids] * self.retrieval[src])',
        "pass",
        "no retrieval on up-move",
    ),
    (
        "sim/engine.py",
        "wait = np.maximum(0.0, self.copy_ready[arch] - hour0)",
        "wait = np.zeros(len(arch))",
        "archived reads never wait",
    ),
    (
        "sim/engine.py",
        "none = self.copy_expire[arch] <= hour0",
        "none = self.copy_expire[arch] < hour0",
        "copy usable at its expiry hour",
    ),
    (
        "sim/engine.py",
        "billable_gb = np.maximum(self.sizes[None, :], min_bytes[:, None]) / BYTES_PER_GB",
        "billable_gb = np.repeat(self.sizes[None, :], len(names), axis=0) / BYTES_PER_GB",
        "no minimum billable size",
    ),
    (
        "sim/engine.py",
        "at_tier_kb = kb - other_kb",
        "at_tier_kb = kb",
        "overhead fully at tier rate",
    ),
    ("sim/engine.py", "if self.copy_write_fee:", "if False:", "Azure copy write not charged"),
    (
        "sim/engine.py",
        'self.ledger.charge("transition", day, ids, np.full(len(ids), self.down_fee[dst]))',
        'self.ledger.charge("transition", day, ids, np.full(len(ids), self.down_fee[src]))',
        "down fee on source",
    ),
    (
        "sim/engine.py",
        "fees = self.read_fee[self.cur[again]]",
        "fees = 0 * self.read_fee[self.cur[again]]",
        "reissue free on AWS",
    ),
    ("sim/rules.py", "BYTES_PER_GB = 2**30", "BYTES_PER_GB = 10**9", "decimal GB"),
    (
        "sim/rules.py",
        "return np.full(n_days, 24 / 730)",
        "return np.full(n_days, 1 / 30)",
        "Google daily = /30",
    ),
    (
        "sim/rules.py",
        'return tier_field(sheet, tier, field + "_low", high)',
        "return high",
        "low restore ignored",
    ),
    (
        "sim/managed.py",
        "idle = day - last - 1\n        tier = np.zeros(n, dtype=np.int64)\n        tier[idle >= d_inf] = 1",
        "idle = day - last\n        tier = np.zeros(n, dtype=np.int64)\n        tier[idle >= d_inf] = 1",
        "IT idle off by one",
    ),
    (
        "sim/managed.py",
        "        tier[~eligible] = 0\n\n        if warm_by_day is not None:",
        "\n        if warm_by_day is not None:",
        "IT small objects tier",
    ),
    (
        "sim/managed.py",
        "charged_up = np.array([False, False, True, True])",
        "charged_up = np.array([False, True, True, True])",
        "Autoclass Nearline->Standard charged",
    ),
    (
        "sim/managed.py",
        'fee_per_day = x["autoclass_management_per_1000_objects"] / 1000 / 30',
        'fee_per_day = x["autoclass_management_per_1000_objects"] / 1000 / 31',
        "Autoclass fee /31",
    ),
    (
        "sim/engine.py",
        "ids = np.flatnonzero(self.created <= day)",
        "ids = np.arange(len(self.sizes))",
        "storage billed before creation",
    ),
    (
        "sim/engine.py",
        'self.ledger.charge("write_requests", day, ids, self.write_fee[self.cur[ids]])',
        "pass",
        "upload not charged",
    ),
    (
        "sim/engine.py",
        "moved = np.flatnonzero((new != self.cur) & (self.created < day))",
        "moved = np.flatnonzero(new != self.cur)",
        "moves charged before creation",
    ),
    # ---- Phase 4: data, policies and the E1 rules
    (
        "policies/scenario.py",
        "MAX_AHEAD = LAG - 1",
        "MAX_AHEAD = LAG",
        "seasonal forecast sees today",
    ),
    # Weakening only ``year >= SEALED_FROM_YEAR`` changes nothing (the max_year guard still refuses
    # 2024), so this planted bug removes the lock on 2024 entirely.
    ("data/sealed.py", "SEALED_FROM_YEAR = 2024", "SEALED_FROM_YEAR = 2025", "2024 not sealed"),
    (
        "data/mapping.py",
        "date(TUNING_YEAR, 12, 31)",
        "date(TUNING_YEAR + 1, 12, 31)",
        "read scale calibrated on 2023",
    ),
    (
        "data/mapping.py",
        "[seed, DATASET_CODE.get(demand.dataset, 0), year, SETTING_CODE[setting]]",
        "[seed, DATASET_CODE.get(demand.dataset, 0), SETTING_CODE[setting]]",
        "read draw not fixed per year",
    ),
    (
        "policies/policies.py",
        "recent = scn.read_within(-self.recency, -1)",
        "recent = scn.read_within(-self.recency, 0)",
        "warm/cold recency sees today",
    ),
    (
        "policies/planner.py",
        "            scn.reads_sum(-horizon, -1),",
        "            scn.reads_sum(-horizon, 0),",
        "reactive planner sees today",
    ),
    (
        "policies/planner.py",
        "return scn.last_year_within(1, self.lead)",
        "return scn.read_within(1, self.lead)",
        "IT pre-warm uses the true future",
    ),
    (
        "policies/policies.py",
        "        tier[scn.small()] = 0",
        "        pass",
        "small objects leave Standard",
    ),
    (
        "policies/policies.py",
        "AUTO_UP_EVERY = 30",
        "AUTO_UP_EVERY = 1",
        "Azure auto-return unlimited",
    ),
    (
        "policies/scenario.py",
        'fee = float(self.sheet.extras["other_operations_per_1000"].value) / 1000',
        "fee = 0.0",
        "Azure access tracking free",
    ),
    (
        "sim/managed.py",
        'ledger.charge("restore_requests", day, asked, np.full(len(asked), put_fee))',
        'ledger.charge("restore_requests", day, asked, np.full(len(asked), 0.0))',
        "forecast restores free",
    ),
    (
        "experiments/select.py",
        'limit = min(cap, rival["cold_rate"])',
        "limit = cap",
        "ours may wait more than rival",
    ),
    (
        "experiments/select.py",
        'line[f"{role}_wait_ok"] = row["cold_rate"] <= rival["cold_rate"] + TOL',
        'line[f"{role}_wait_ok"] = True',
        "2023 waiting check skipped",
    ),
    (
        "experiments/select.py",
        "GAP_TO_PASS = 0.05",
        "GAP_TO_PASS = 0.04",
        "pass threshold below 5%",
    ),  # ---- Round two: gate R1 (docs/R1_PROTOCOL.md)
    (
        "experiments/r1.py",
        'hist = load_run(dataset, year - 1, "actual")',
        'hist = load_run(dataset, year, "actual")',
        "chooser sees the scored year",
    ),
    (
        "experiments/r1.py",
        "REPLICATE_OFFSET = 100",
        "REPLICATE_OFFSET = 0",
        "ceiling chooses on the scored draw",
    ),
    (
        "experiments/r1.py",
        'limit = min(cap, rival["cold_rate"]) if rule == "matched" else cap',
        "limit = cap",
        "R1 ours may wait more than rival",
    ),
    (
        "experiments/r1.py",
        'OURS = ("seasonal", "chooser")',
        'OURS = ("seasonal", "chooser", "ceiling")',
        "ceiling counted as ours",
    ),
    (
        "experiments/r1.py",
        "if len(pair_lines) == len(PAIRS) and all(test(x) for x in pair_lines):",
        "if any(test(x) for x in pair_lines):",
        "R1 passes on one rolling year",
    ),
    (
        "experiments/r1.py",
        "end = (date(year, 12, 31) - f.start).days + 1",
        "end = (date(year + 1, 12, 31) - f.start).days + 1",
        "rolling year sees the next year",
    ),
    (
        "experiments/chooser.py",
        "cost=float(cost[choice, cols].sum()) + switch_cost,",
        "cost=float(cost[choice, cols].sum()),",
        "switches free",
    ),
    (
        "experiments/chooser.py",
        "choice: IntArray = np.where(better & has_history, best, prior).astype(np.int64)",
        "choice: IntArray = np.where(better, best, prior).astype(np.int64)",
        "files without history chosen on zeros",
    ),
    (
        "sim/engine.py",
        "self.wait_hours_by_object[arch] += wait * ca * self.weight[arch]",
        "self.wait_hours_by_object[arch] += wait * self.weight[arch]",
        "per-file wait hours miss read counts",
    ),
]
# Never write or reuse compiled caches. A planted bug of the same byte size, restored within the same
# second, would otherwise survive in __pycache__ and leak into later test runs (seen 2026-10-30).
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def clear_caches() -> None:
    for cache in (root / "src").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


clear_caches()
killed = 0
for fname, old, new, label in M:
    p = root / "src/sat" / fname
    src = p.read_text()
    if src.count(old) != 1:
        print(f"BROKEN (pattern must occur once): {label}")
        continue
    p.write_text(src.replace(old, new, 1))
    try:
        res = subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
                "tests/test_sim_hand.py",
                "tests/test_sim_calculator.py",
                "tests/test_sim_properties.py",
                "tests/test_sim_window.py",
                "tests/test_policies.py",
                "tests/test_data_phase4.py",
                "tests/test_selection.py",
                "tests/test_round2.py",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            env=ENV,
        )
    finally:
        p.write_text(src)
        clear_caches()
    caught = res.returncode != 0
    killed += caught
    print(("CAUGHT  " if caught else "MISSED  ") + label)
print(f"{killed}/{len(M)} deliberate bugs caught")
sys.exit(0 if killed == len(M) else 1)
