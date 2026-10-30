"""Fee-aware placement (``Planner``) and Intelligent-Tiering with forecast restores (``ITPrewarm``).

Added after the synthetic tuning run showed that a fee-blind warm/cold rule cannot compete with
services that move data for free (D-034). Both keep the forecast as the only thing that changes
between ``seasonal``, ``reactive`` and ``oracle``:

* seasonal: the next H days will look like the same H days last year (lag 364, weekday-aligned),
  or like the last H days if those were busier (seasonal-naive with a recency floor: objects that
  did not exist or were quiet a year ago are not forecast as unread while being read);
* reactive: the next H days will look like the last H days;
* oracle: the true next H days (a reference, not a policy anyone can run).

``Planner``: every day, for every object, estimate the cost per day of each allowed class given the
forecast for the next H days (storage with the minimum billable size and archive overhead; reads
with their retrieval fees; restores for archive classes), add the one-off cost of moving there now
(transition or restore, and early deletion of the class it leaves) spread over the time the move
commits to (the horizon or the class's minimum duration, whichever is longer), and choose the
cheapest. An archive class is not allowed while a read is expected within the next ``lead`` days, so
data the forecast expects is warmed ahead of time. The estimate only guides the choice; the
simulator bills the resulting plan exactly.

``ITPrewarm`` (AWS): objects live in S3 Intelligent-Tiering with its archive tiers switched on, and
the policy restores an archived object when the forecast expects a read within ``lead`` days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from sat.policies.policies import Policy, _sim_config, _small_rule
from sat.policies.rules import check_aws_plan
from sat.policies.scenario import BoolArray, FloatArray, IntArray, Scenario
from sat.sim import ITConfig, Plan, SimResult, simulate
from sat.sim.managed import simulate_intelligent_tiering
from sat.sim.rules import BYTES_PER_GB, BYTES_PER_KB, rules_for, tier_field

DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class _Costs:
    """Per-class cost estimates, arrays of shape (classes, objects) unless noted."""

    daily: FloatArray  # storage per day
    per_read: FloatArray  # online classes: request + retrieval per read
    per_read_day: FloatArray  # archive classes: one restore (request + retrieval + copy day)
    archive: BoolArray  # (classes,)
    min_days: FloatArray  # (classes,)
    down_fee: FloatArray  # (classes,) moving into this class from above
    up_cost: FloatArray  # leaving this class upwards


def _costs(scn: Scenario, classes: tuple[str, ...]) -> _Costs:
    sheet, rules = scn.sheet, rules_for(scn.sheet)
    size_gb = scn.sizes / BYTES_PER_GB
    first = scn.sheet.tier_order[0]
    n = scn.n_objects
    daily, per_read, per_read_day, up_cost = (np.zeros((len(classes), n)) for _ in range(4))
    archive = np.zeros(len(classes), dtype=bool)
    min_days, down_fee = np.zeros(len(classes)), np.zeros(len(classes))
    copy_price = sheet.get(rules.copy_tier, "storage_usd_per_gb_month") if rules.copy_tier else 0.0
    for k, t in enumerate(classes):
        price = sheet.get(t, "storage_usd_per_gb_month")
        billable = np.maximum(
            scn.sizes, tier_field(sheet, t, "min_billable_object_kb") * BYTES_PER_KB
        )
        overhead_kb = tier_field(sheet, t, "per_object_overhead_kb")
        other_kb = min(rules.overhead_other_kb, overhead_kb)
        other_price = (
            sheet.get(rules.overhead_other_tier, "storage_usd_per_gb_month")
            if rules.overhead_other_tier and other_kb
            else 0.0
        )
        overhead = ((overhead_kb - other_kb) * price + other_kb * other_price) * BYTES_PER_KB
        daily[k] = (billable * price + overhead) / BYTES_PER_GB / DAYS_PER_MONTH
        retrieval = tier_field(sheet, t, "retrieval_usd_per_gb")
        read_fee = tier_field(sheet, t, rules.read_field) / 1000
        archive[k] = tier_field(sheet, t, "restore_hours") > 0
        min_days[k] = tier_field(sheet, t, "min_storage_days")
        down_fee[k] = tier_field(sheet, t, rules.down_fee_field) / 1000
        if archive[k]:
            restore_fee = tier_field(sheet, t, rules.restore_fee_by_speed["standard"]) / 1000
            restore_gb = tier_field(sheet, t, rules.retrieval_by_speed["standard"])
            first_read = tier_field(sheet, first, rules.read_field) / 1000
            per_read[k] = first_read
            per_read_day[k] = restore_fee + size_gb * restore_gb + size_gb * copy_price / 30
            up_cost[k] = per_read_day[k] + tier_field(sheet, first, rules.write_field) / 1000
        else:
            per_read[k] = read_fee + size_gb * retrieval
            up_fee_tier = t if rules.up_fee_on == "source" else first
            up_cost[k] = (
                tier_field(sheet, up_fee_tier, rules.up_fee_field) / 1000 + size_gb * retrieval
            )
    return _Costs(daily, per_read, per_read_day, archive, min_days, down_fee, up_cost)


def _forecast(scn: Scenario, kind: str, horizon: int, lead: int) -> tuple[Any, Any, BoolArray]:
    """(expected reads, expected read days) over the next ``horizon`` days, and whether a read is
    expected within ``lead`` days, for each object and window day."""
    if kind == "seasonal":
        # last year's same days, or the recent past if that was busier: an object with no history a
        # year ago (new, or quiet then) must not be forecast as unread while it is being read
        return (
            np.maximum(scn.last_year_reads_sum(0, horizon - 1), scn.reads_sum(-horizon, -1)),
            np.maximum(
                scn.last_year_read_days_sum(0, horizon - 1), scn.read_days_sum(-horizon, -1)
            ),
            scn.last_year_within(0, lead) | scn.read_within(-lead, -1),
        )
    if kind == "oracle":
        return (
            scn.reads_sum(0, horizon - 1),
            scn.read_days_sum(0, horizon - 1),
            scn.read_within(0, lead),
        )
    if kind == "reactive":
        return (
            scn.reads_sum(-horizon, -1),
            scn.read_days_sum(-horizon, -1),
            scn.read_within(-lead, -1),
        )
    raise ValueError(f"unknown forecast {kind!r}")


@dataclass(frozen=True)
class Planner(Policy):
    kind: str  # "seasonal", "reactive" or "oracle"
    classes: tuple[str, ...]
    horizon: int = 90
    lead: int = 7

    def __post_init__(self) -> None:
        if self.kind not in {"seasonal", "reactive", "oracle"}:
            raise ValueError(f"unknown kind {self.kind!r}")
        if not 1 <= self.horizon <= 364 or not 1 <= self.lead <= 363:
            raise ValueError("horizon must be 1..364 days and lead 1..363")

    @property
    def family(self) -> str:
        return self.kind

    @property
    def name(self) -> str:
        return f"{self.kind}-planner:{'/'.join(self.classes)}:h{self.horizon}:lead{self.lead}"

    def params(self) -> dict[str, Any]:
        return {"classes": list(self.classes), "horizon": self.horizon, "lead": self.lead}

    def tiers(self, scn: Scenario) -> IntArray:
        costs = _costs(scn, self.classes)
        reads, read_days, near = _forecast(scn, self.kind, self.horizon, self.lead)
        index = np.array([scn.tier_index(t) for t in self.classes])
        if (np.diff(index) <= 0).any():
            raise ValueError("classes must be listed from warmest to coldest")
        h = float(self.horizon)
        # moving into a class commits to it for its minimum duration (at least the horizon), so a
        # move's one-off cost is spread over that span; classes are compared by cost per day
        span = np.maximum(h, costs.min_days)
        keeps_clock = rules_for(scn.sheet).lifecycle_keeps_clock
        n, n_cls = scn.n_objects, len(self.classes)
        created = scn.created_rel()
        cur = np.zeros(n, dtype=np.int64)  # position in self.classes
        entered = np.full(n, -(10**6), dtype=np.int64)
        out = np.empty((n, scn.n_days), dtype=np.int64)
        rows = np.arange(n)
        for w in range(scn.n_days):
            f, fd, soon = reads[:, w] / h, read_days[:, w] / h, near[:, w]
            rate = costs.daily + f[None, :] * costs.per_read + fd[None, :] * costs.per_read_day
            rate[costs.archive] = np.where(soon[None, :], np.inf, rate[costs.archive])
            fresh = (created == w) | (w == 0)
            age = w - entered
            leave = np.maximum(0.0, costs.min_days[cur] - age) * costs.daily[cur, rows]
            for k in range(n_cls):
                moving = (cur != k) & ~fresh
                down = k > cur
                early = np.where(down & keeps_clock, 0.0, leave)
                switch = np.where(down, costs.down_fee[k], costs.up_cost[cur, rows]) + early
                rate[k] += np.where(moving, switch / span[k], 0.0)
            choice = rate.argmin(axis=0)
            changed = (choice != cur) | fresh
            entered = np.where(changed, w, entered)
            cur = choice
            out[:, w] = index[cur]
        return _small_rule(scn, out)

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        plan = Plan(self.tiers(scn))
        if scn.sheet.cloud == "aws":
            check_aws_plan(scn, plan)
        result = simulate(
            scn.sheet, scn.inventory(), scn.window_reads(), plan, scn.window_start, _sim_config(scn)
        )
        scn.observation_charge(result, per_object_day=scn.sheet.cloud == "azure")
        return result


@dataclass(frozen=True)
class ITPrewarm(Policy):
    """S3 Intelligent-Tiering with archive tiers, plus restores ahead of forecast reads."""

    kind: str  # "seasonal" or "oracle"
    archive_days: int = 90
    deep_archive_days: int | None = 180
    lead: int = 7

    def __post_init__(self) -> None:
        if self.kind not in {"seasonal", "oracle"}:
            raise ValueError(f"unknown kind {self.kind!r}")
        if not 1 <= self.lead <= 363:
            raise ValueError("lead must be 1..363")

    @property
    def family(self) -> str:
        return self.kind

    @property
    def name(self) -> str:
        deep = f":deep@{self.deep_archive_days}d" if self.deep_archive_days else ""
        return f"{self.kind}-it-prewarm:archive@{self.archive_days}d{deep}:lead{self.lead}"

    def params(self) -> dict[str, Any]:
        return {
            "archive_days": self.archive_days,
            "deep_archive_days": self.deep_archive_days,
            "lead": self.lead,
        }

    def prewarm(self, scn: Scenario) -> BoolArray:
        if self.kind == "seasonal":
            return scn.last_year_within(1, self.lead)
        return scn.read_within(1, self.lead)

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        result = simulate_intelligent_tiering(
            scn.sheet,
            scn.inventory(),
            scn.window_reads(),
            scn.window_start,
            ITConfig(self.archive_days, self.deep_archive_days),
            initial_idle_days=scn.initial_idle_days(),
            restore_time=scn.restore_time,
            measure_from=scn.measure_from,
            prewarm=self.prewarm(scn),
        )
        scn.observation_charge(result, per_object_day=False)
        return result
