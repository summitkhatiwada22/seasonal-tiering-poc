# ruff: noqa: E501
"""Gate G2 check of the checks: plant one deliberate bug at a time in the simulator and confirm the
simulator tests fail. Every planted bug must be caught. Run: ``uv run python scripts/mutation_check.py``.

The source file is always restored, even if a test run crashes.
"""

import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
M = [
    (
        "engine.py",
        "np.ceil((ready + 24.0 * keep) / 24.0 - 1e-9) * 24.0",
        "(ready + 24.0 * keep)",
        "copy expiry not rounded to midnight",
    ),
    (
        "engine.py",
        "remaining * self.price[src] * self.early_gb[src, ids] * leave_factor",
        "remaining * self.price[src] * self.early_gb[src, ids] / 30",
        "early deletion always /30",
    ),
    (
        "engine.py",
        "keeps_clock = down and self.rules.lifecycle_keeps_clock",
        "keeps_clock = False",
        "Google lifecycle resets clock",
    ),
    (
        "engine.py",
        'fee = self.up_fee[dst] if self.rules.up_fee_on == "dest" else self.up_fee[src]',
        "fee = self.up_fee[dst]",
        "Azure up-move fee on destination",
    ),
    (
        "engine.py",
        'self.ledger.charge("retrieval", day, ids, self.size_gb[ids] * self.retrieval[src])',
        "pass",
        "no retrieval on up-move",
    ),
    (
        "engine.py",
        "wait = np.maximum(0.0, self.copy_ready[arch] - hour0)",
        "wait = np.zeros(len(arch))",
        "archived reads never wait",
    ),
    (
        "engine.py",
        "none = self.copy_expire[arch] <= hour0",
        "none = self.copy_expire[arch] < hour0",
        "copy usable at its expiry hour",
    ),
    (
        "engine.py",
        "billable_gb = np.maximum(self.sizes[None, :], min_bytes[:, None]) / BYTES_PER_GB",
        "billable_gb = np.repeat(self.sizes[None, :], len(names), axis=0) / BYTES_PER_GB",
        "no minimum billable size",
    ),
    ("engine.py", "at_tier_kb = kb - other_kb", "at_tier_kb = kb", "overhead fully at tier rate"),
    ("engine.py", "if self.copy_write_fee:", "if False:", "Azure copy write not charged"),
    (
        "engine.py",
        'self.ledger.charge("transition", day, ids, np.full(len(ids), self.down_fee[dst]))',
        'self.ledger.charge("transition", day, ids, np.full(len(ids), self.down_fee[src]))',
        "down fee on source",
    ),
    (
        "engine.py",
        "fees = self.read_fee[self.cur[again]]",
        "fees = 0 * self.read_fee[self.cur[again]]",
        "reissue free on AWS",
    ),
    ("rules.py", "BYTES_PER_GB = 2**30", "BYTES_PER_GB = 10**9", "decimal GB"),
    (
        "rules.py",
        "return np.full(n_days, 24 / 730)",
        "return np.full(n_days, 1 / 30)",
        "Google daily = /30",
    ),
    (
        "rules.py",
        'return tier_field(sheet, tier, field + "_low", high)',
        "return high",
        "low restore ignored",
    ),
    (
        "managed.py",
        "idle = day - last - 1\n        tier = np.zeros(n, dtype=np.int64)\n        tier[idle >= d_inf] = 1",
        "idle = day - last\n        tier = np.zeros(n, dtype=np.int64)\n        tier[idle >= d_inf] = 1",
        "IT idle off by one",
    ),
    (
        "managed.py",
        'tier[~eligible] = 0\n\n        counts = reads_by_day[day]\n        ids = np.flatnonzero(counts)\n        if len(ids):\n            c = counts[ids]\n            waits.reads += float((c * weight[ids]).sum())\n            ledger.charge("read_requests", day, ids, c * get_fee)',
        'counts = reads_by_day[day]\n        ids = np.flatnonzero(counts)\n        if len(ids):\n            c = counts[ids]\n            waits.reads += float((c * weight[ids]).sum())\n            ledger.charge("read_requests", day, ids, c * get_fee)',
        "IT small objects tier",
    ),
    (
        "managed.py",
        "charged_up = np.array([False, False, True, True])",
        "charged_up = np.array([False, True, True, True])",
        "Autoclass Nearline->Standard charged",
    ),
    (
        "managed.py",
        'fee_per_day = x["autoclass_management_per_1000_objects"] / 1000 / 30',
        'fee_per_day = x["autoclass_management_per_1000_objects"] / 1000 / 31',
        "Autoclass fee /31",
    ),
    (
        "engine.py",
        "ids = np.flatnonzero(self.created <= day)",
        "ids = np.arange(len(self.sizes))",
        "storage billed before creation",
    ),
    (
        "engine.py",
        'self.ledger.charge("write_requests", day, ids, self.write_fee[self.cur[ids]])',
        "pass",
        "upload not charged",
    ),
    (
        "engine.py",
        "moved = np.flatnonzero((new != self.cur) & (self.created < day))",
        "moved = np.flatnonzero(new != self.cur)",
        "moves charged before creation",
    ),
]
killed = 0
for fname, old, new, label in M:
    p = root / "src/sat/sim" / fname
    src = p.read_text()
    if old not in src:
        print(f"SKIP (pattern missing): {label}")
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
                "tests/test_sim_hand.py",
                "tests/test_sim_calculator.py",
                "tests/test_sim_properties.py",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
    finally:
        p.write_text(src)
    caught = res.returncode != 0
    killed += caught
    print(("CAUGHT  " if caught else "MISSED  ") + label)
print(f"{killed}/{len(M)} deliberate bugs caught")
sys.exit(0 if killed == len(M) else 1)
