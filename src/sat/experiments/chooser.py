"""The per-file chooser (round two, docs/R1_PROTOCOL.md, D-045).

Every policy in the round-two grid is run on every object. Objects never interact in the
simulator, so a plan that gives each object its own policy costs exactly the sum of each object's
cost under its policy. The chooser decides, once a year and for each file, which policy it follows
next year:

    score[p, i] = cost of file i under policy p in the history year
                  + mu x reads of file i that waited under p in the history year
                  + switch charge, if p differs from the policy file i followed this year

It picks the lowest score, but keeps the file on its current policy unless the best score is lower
by more than ``margin`` of the current one. Files with no history stay on the default (S3
Intelligent-Tiering without archive tiers, the policy a customer would use otherwise).

* ``chooser`` (ours): the history year is the year before (causal: it uses only the past).
* ``ceiling`` (reference): the history is an independent random draw of the scored year's reads
  from the same true expected rates. It knows each file's true expected rate, not the draw that is
  scored: the forecastable ceiling.

The fee arithmetic is the simulator's, not an estimate; the only modelled part is the switch
charge, billed at an upper bound (``switch_charge``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sat.prices import PriceSheet
from sat.sim.rules import BYTES_PER_GB, rules_for, tier_field

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

DEFAULT_POLICY = "intelligent-tiering"
MUS = (0.0, 0.001, 0.01, 0.1, 1.0, 10.0)  # USD per read that waited in the history year
MARGINS = (0.0, 0.1, 0.25)
DAYS_PER_MONTH = 30.0  # early deletion is billed per 30-day month on AWS


@dataclass(frozen=True)
class Setting:
    menu: str  # "all": every policy in the grid; "online": only policies under which no read waits
    mu: float
    margin: float

    def __post_init__(self) -> None:
        if self.menu not in {"all", "online"}:
            raise ValueError(f"unknown menu {self.menu!r}")
        if self.mu < 0 or not 0 <= self.margin < 1:
            raise ValueError("mu must be >= 0 and margin in [0, 1)")

    @property
    def name(self) -> str:
        return f"{self.menu}:mu{self.mu:g}:m{self.margin:g}"


SETTINGS: tuple[Setting, ...] = tuple(
    [Setting("online", 0.0, m) for m in MARGINS]
    + [Setting("all", mu, m) for mu in MUS for m in MARGINS]
)


def switch_charge(sheet: PriceSheet, sizes: IntArray) -> FloatArray:
    """Upper bound (USD) for moving one file from one policy to another at the year boundary.

    It adds the dearest of every one-off cost a move can trigger on this price sheet: reading the
    whole file out (largest per-GB retrieval or standard restore fee), the largest per-request
    fee (transition, restore or write), and early deletion for the longest minimum storage duration
    at that class's price. A real switch costs at most this.
    """
    rules = rules_for(sheet)
    per_gb, per_req, early = 0.0, 0.0, 0.0
    for t in sheet.tier_order:
        per_gb = max(per_gb, tier_field(sheet, t, "retrieval_usd_per_gb"))
        if rules.retrieval_by_speed and tier_field(sheet, t, "restore_hours") > 0:
            per_gb = max(per_gb, tier_field(sheet, t, rules.retrieval_by_speed["standard"]))
            per_req = max(
                per_req, tier_field(sheet, t, rules.restore_fee_by_speed["standard"]) / 1000
            )
        per_req = max(per_req, tier_field(sheet, t, rules.down_fee_field) / 1000)
        per_req = max(per_req, tier_field(sheet, t, rules.write_field) / 1000)
        price = sheet.get(t, "storage_usd_per_gb_month")
        early = max(early, tier_field(sheet, t, "min_storage_days") / DAYS_PER_MONTH * price)
    size_gb = sizes / BYTES_PER_GB
    out: FloatArray = size_gb * (per_gb + early) + per_req
    return out


def choose(
    cost: FloatArray,
    cold: FloatArray,
    allowed: BoolArray,
    prior: IntArray,
    has_history: BoolArray,
    switch: FloatArray,
    setting: Setting,
) -> IntArray:
    """Policy index per file. ``cost`` and ``cold`` are (policies, files) from the history year;
    ``prior`` is each file's current policy (which must be allowed)."""
    n_pol, n = cost.shape
    if cold.shape != (n_pol, n) or allowed.shape != (n_pol,) or prior.shape != (n,):
        raise ValueError("shape mismatch")
    if not allowed[prior].all():
        raise ValueError("every file's current policy must be in the menu")
    cols = np.arange(n)
    score = cost + setting.mu * cold
    score = score + (np.arange(n_pol)[:, None] != prior[None, :]) * switch[None, :]
    score = np.where(allowed[:, None], score, np.inf)
    best = np.argmin(score, axis=0)
    current = score[prior, cols]
    better = score[best, cols] < (1.0 - setting.margin) * current - 1e-15
    choice: IntArray = np.where(better & has_history, best, prior).astype(np.int64)
    return choice


@dataclass(frozen=True)
class Outcome:
    cost: float
    reads: float
    cold_reads: float
    wait_hours: float
    max_wait_hours: float
    switches: int
    switch_cost: float

    @property
    def cold_rate(self) -> float:
        return self.cold_reads / self.reads if self.reads else 0.0


def outcome(
    cost: FloatArray,
    cold: FloatArray,
    wait_hours: FloatArray,
    max_wait: FloatArray,
    reads: FloatArray,
    choice: IntArray,
    prior: IntArray,
    switch: FloatArray,
) -> Outcome:
    """The scored year's bill and waits when each file follows ``choice`` (arrays: policies x
    files, ``reads`` per file). Files whose policy changed pay the switch charge."""
    cols = np.arange(cost.shape[1])
    moved = choice != prior
    switch_cost = float(switch[moved].sum())
    return Outcome(
        cost=float(cost[choice, cols].sum()) + switch_cost,
        reads=float(reads.sum()),
        cold_reads=float(cold[choice, cols].sum()),
        wait_hours=float(wait_hours[choice, cols].sum()),
        max_wait_hours=float(max_wait[choice, cols].max(initial=0.0)),
        switches=int(moved.sum()),
        switch_cost=switch_cost,
    )
