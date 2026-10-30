"""The storage policies compared in early check E1 (docs/POLICIES.md describes each one).

Rivals (what a customer can switch on today):
* ``Lifecycle``: age-based rules ("move to class X N days after upload"); for objects stored long
  before the window this is the same as keeping everything in X. ``all-<class>`` is the special case
  with no transition.
* ``IntelligentTiering`` (AWS) and ``Autoclass`` (Google): the providers' reactive services,
  billed by ``sat.sim.managed``.
* ``AzureLastAccess``: Azure lifecycle rules on days since last access, with automatic return from
  cool to hot on access. Azure's own automatic tiering ("smart tier") has no LRS price.

Ours, all built on one two-class state machine (``TwoTier``):
* ``seasonal``: seasonal-naive. An object is warm on day d if it was read in the matching days
  last year (d-364 to d-364+lead, weekday-aligned) or in the last ``recency`` days. It goes cold
  only when last year's same period shows no read for the cold class's minimum storage duration.
* ``reactive``: the same machine with the seasonal part switched off (recency only). It shows how
  much of any gain comes from seasonality rather than from simply reacting to reads.
* ``oracle``: the same machine fed the true future reads ("perfect forecast"). A reference for how
  much any forecast could add to this policy, not a policy anyone can run.

Two ways to warm an object kept in an archive class (AWS Glacier Flexible / Deep Archive, Azure
Archive): ``move`` it to the warm class (restore and copy, early deletion of the archive copy), or
``copy`` mode: leave it archived and ask for a temporary restored copy for the predicted window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from sat.policies.rules import check_aws_plan
from sat.policies.scenario import MAX_AHEAD, BoolArray, IntArray, Scenario, runs
from sat.sim import ITConfig, Plan, Restore, SimConfig, SimResult, simulate
from sat.sim.managed import simulate_autoclass, simulate_intelligent_tiering

AUTO_UP_EVERY = 30  # Azure: enableAutoTierToHotFromCool moves a blob "only one time in 30 days"

RIVAL_FAMILIES = ("lifecycle", "managed", "access-lifecycle")


def _sim_config(scn: Scenario, keep_days: int = 1) -> SimConfig:
    return SimConfig(
        restore_time=scn.restore_time,
        measure_from=scn.measure_from,
        on_demand_keep_days=keep_days,
    )


def _small_rule(scn: Scenario, tier: IntArray) -> IntArray:
    """AWS lifecycle default: objects under 128 KB never leave the first class (D-033)."""
    if scn.sheet.cloud == "aws":
        tier[scn.small()] = 0
    return tier


@dataclass(frozen=True)
class Policy:
    cloud: str

    @property
    def family(self) -> str:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    def params(self) -> dict[str, Any]:
        return {}

    def run(self, scn: Scenario) -> SimResult:
        raise NotImplementedError

    def _check(self, scn: Scenario) -> None:
        if scn.sheet.cloud != self.cloud:
            raise ValueError(f"{self.name} is a {self.cloud} policy, scenario is {scn.sheet.cloud}")


# ------------------------------------------------------------------------------ rivals


@dataclass(frozen=True)
class Lifecycle(Policy):
    target: str  # class reached after ``after_days`` (the first class = keep everything there)
    after_days: int = 30

    @property
    def family(self) -> str:
        return "lifecycle"

    @property
    def name(self) -> str:
        first = _first_class(self.cloud)
        if self.target == first:
            return f"all-{first}"
        return f"lifecycle:{self.target}@{self.after_days}d"

    def params(self) -> dict[str, Any]:
        return {"target": self.target, "after_days": self.after_days}

    def tiers(self, scn: Scenario) -> IntArray:
        age = (scn.sim_start + np.arange(scn.n_days))[None, :] - scn.created[:, None]
        target = scn.tier_index(self.target)
        tier = np.where(age >= self.after_days, target, 0).astype(np.int64)
        return _small_rule(scn, tier)

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        plan = Plan(self.tiers(scn))
        if scn.sheet.cloud == "aws":
            check_aws_plan(scn, plan)
        return simulate(
            scn.sheet, scn.inventory(), scn.window_reads(), plan, scn.window_start, _sim_config(scn)
        )


@dataclass(frozen=True)
class IntelligentTiering(Policy):
    archive_days: int | None = None
    deep_archive_days: int | None = None

    @property
    def family(self) -> str:
        return "managed"

    @property
    def name(self) -> str:
        parts = ["intelligent-tiering"]
        if self.archive_days:
            parts.append(f"archive@{self.archive_days}d")
        if self.deep_archive_days:
            parts.append(f"deep@{self.deep_archive_days}d")
        return ":".join(parts)

    def params(self) -> dict[str, Any]:
        return {"archive_days": self.archive_days, "deep_archive_days": self.deep_archive_days}

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        return simulate_intelligent_tiering(
            scn.sheet,
            scn.inventory(),
            scn.window_reads(),
            scn.window_start,
            ITConfig(self.archive_days, self.deep_archive_days),
            initial_idle_days=scn.initial_idle_days(),
            restore_time=scn.restore_time,
            measure_from=scn.measure_from,
        )


@dataclass(frozen=True)
class Autoclass(Policy):
    terminal: str = "nearline"

    @property
    def family(self) -> str:
        return "managed"

    @property
    def name(self) -> str:
        return f"autoclass:{self.terminal}"

    def params(self) -> dict[str, Any]:
        return {"terminal": self.terminal}

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        return simulate_autoclass(
            scn.sheet,
            scn.inventory(),
            scn.window_reads(),
            scn.window_start,
            terminal=self.terminal,
            initial_idle_days=scn.initial_idle_days(),
            measure_from=scn.measure_from,
        )


@dataclass(frozen=True)
class AzureLastAccess(Policy):
    """Azure lifecycle on last access (daysAfterLastAccessTimeGreaterThan), auto-return to hot."""

    cool_days: int
    cold_days: int | None = None
    archive_days: int | None = None

    @property
    def family(self) -> str:
        return "access-lifecycle"

    @property
    def name(self) -> str:
        parts = [f"cool@{self.cool_days}d"]
        if self.cold_days:
            parts.append(f"cold@{self.cold_days}d")
        if self.archive_days:
            parts.append(f"archive@{self.archive_days}d")
        return "azure-last-access:" + ",".join(parts)

    def params(self) -> dict[str, Any]:
        return {"cool": self.cool_days, "cold": self.cold_days, "archive": self.archive_days}

    def tiers(self, scn: Scenario) -> IntArray:
        hot, cool = scn.tier_index("hot"), scn.tier_index("cool")
        cold, arch = scn.tier_index("cold"), scn.tier_index("archive")
        read = scn.reads[:, : scn.end] > 0
        n = scn.n_objects
        cur = np.full(n, hot, dtype=np.int64)
        last_access = scn.created.astype(np.int64) - 1  # an upload counts as an access
        last_up = np.full(n, -(10**6), dtype=np.int64)
        out = np.empty((n, scn.n_days), dtype=np.int64)
        for a in range(scn.end):
            if a > 0:  # an access yesterday returns a cool blob to hot (at most once in 30 days)
                up = (cur == cool) & read[:, a - 1] & (a - last_up >= AUTO_UP_EVERY)
                cur[up] = hot
                last_up[up] = a
            idle = a - last_access - 1  # "days after last access" greater than N <=> idle >= N
            target = np.full(n, hot, dtype=np.int64)
            target[idle >= self.cool_days] = cool
            if self.cold_days is not None:
                target[idle >= self.cold_days] = cold
            if self.archive_days is not None:
                target[idle >= self.archive_days] = arch
            cur = np.maximum(cur, target)  # lifecycle only moves blobs down
            if a >= scn.sim_start:
                out[:, a - scn.sim_start] = cur
            # an archived blob is never accessed (it is read through a rehydrated copy)
            accessed = read[:, a] & (cur != arch)
            last_access[accessed] = a
        return out

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        plan = Plan(self.tiers(scn))
        result = simulate(
            scn.sheet, scn.inventory(), scn.window_reads(), plan, scn.window_start, _sim_config(scn)
        )
        scn.observation_charge(result, per_object_day=True)
        return result


# ------------------------------------------------------------------------------ ours


@dataclass(frozen=True)
class TwoTier(Policy):
    kind: str  # "seasonal", "reactive" or "oracle"
    warm: str
    cold: str
    mode: str = "move"  # "move" or "copy" (copy: keep archived, pre-warm with restored copies)
    lead: int = 7  # days ahead a predicted read makes the object warm
    recency: int = 30  # days after a read the object stays warm

    def __post_init__(self) -> None:
        if self.kind not in {"seasonal", "reactive", "oracle"}:
            raise ValueError(f"unknown kind {self.kind!r}")
        if self.mode not in {"move", "copy"}:
            raise ValueError(f"unknown mode {self.mode!r}")
        if not 1 <= self.lead <= MAX_AHEAD or not 0 <= self.recency <= 365:
            raise ValueError("lead must be 1..363 and recency 0..365")

    @property
    def family(self) -> str:
        return self.kind

    @property
    def name(self) -> str:
        tiers = f"{self.cold}+copies" if self.mode == "copy" else f"{self.warm}/{self.cold}"
        if self.kind == "reactive":
            return f"reactive:{tiers}:recent{self.recency}"
        return f"{self.kind}:{tiers}:lead{self.lead}:recent{self.recency}"

    def params(self) -> dict[str, Any]:
        return {
            "warm": self.warm,
            "cold": self.cold,
            "mode": self.mode,
            "lead": self.lead,
            "recency": self.recency,
        }

    def signals(self, scn: Scenario) -> tuple[BoolArray, BoolArray, BoolArray]:
        """(predicted, recent, quiet) for each object and window day.

        predicted: a read is expected within ``lead`` days; recent: read in the last ``recency``
        days; quiet: no read expected for the cold class's whole minimum storage duration."""
        min_cold = scn.min_days(self.cold)
        if self.kind == "seasonal":
            predicted = scn.last_year_within(0, self.lead)
            quiet = ~scn.last_year_within(0, min(min_cold - 1, MAX_AHEAD))
        elif self.kind == "oracle":
            predicted = scn.read_within(0, self.lead)
            quiet = ~scn.read_within(0, min_cold - 1)
        else:
            predicted = np.zeros((scn.n_objects, scn.n_days), dtype=bool)
            quiet = np.ones((scn.n_objects, scn.n_days), dtype=bool)
        if self.recency > 0:
            recent = scn.read_within(-self.recency, -1)
        else:
            recent = np.zeros((scn.n_objects, scn.n_days), dtype=bool)
        return predicted, recent, quiet

    def tiers(
        self, scn: Scenario, signals: tuple[BoolArray, BoolArray, BoolArray] | None = None
    ) -> IntArray:
        predicted, recent, quiet = signals or self.signals(scn)
        want = predicted | recent
        warm_i, cold_i = scn.tier_index(self.warm), scn.tier_index(self.cold)
        min_warm = scn.min_days(self.warm)
        created = scn.created_rel()
        n = scn.n_objects
        is_warm = want[:, 0] | ~quiet[:, 0]
        entered = np.where(created > 0, created, -(10**6))
        out = np.empty((n, scn.n_days), dtype=np.int64)
        for w in range(scn.n_days):
            if w > 0:
                new = created == w
                down = is_warm & ~want[:, w] & quiet[:, w] & (w - entered >= min_warm) & ~new
                up = ~is_warm & want[:, w] & ~new
                is_warm = (is_warm & ~down) | up
                is_warm[new] = want[new, w] | ~quiet[new, w]
                entered[down | up] = w
            out[:, w] = np.where(is_warm, warm_i, cold_i)
        return _small_rule(scn, out)

    def restores(
        self, scn: Scenario, tier: IntArray, predicted: BoolArray | None = None
    ) -> list[Restore]:
        if predicted is None:
            predicted = self.signals(scn)[0]
        cold_i = scn.tier_index(self.cold)
        archived = (tier == cold_i).all(axis=1)
        created = scn.created_rel()
        orders = []
        for obj, first, last in runs(predicted & archived[:, None]):
            first = max(first, int(created[obj]))
            if first <= last:
                orders.append(Restore(obj, first, last - first + 1))
        return orders

    def run(self, scn: Scenario) -> SimResult:
        self._check(scn)
        signals = self.signals(scn)
        if self.mode == "copy":
            if scn.sheet.tiers[self.cold]["restore_hours"].value <= 0:
                raise ValueError(f"copy mode needs an archive class, not {self.cold}")
            tier = _small_rule(scn, np.full((scn.n_objects, scn.n_days), scn.tier_index(self.cold)))
            plan = Plan(tier, self.restores(scn, tier, signals[0]))
            config = _sim_config(scn, keep_days=max(1, self.recency))
        else:
            plan = Plan(self.tiers(scn, signals))
            config = _sim_config(scn)
        if scn.sheet.cloud == "aws":
            check_aws_plan(scn, plan)
        result = simulate(
            scn.sheet, scn.inventory(), scn.window_reads(), plan, scn.window_start, config
        )
        scn.observation_charge(result, per_object_day=scn.sheet.cloud == "azure")
        return result


def _first_class(cloud: str) -> str:
    return {"aws": "standard", "gcs": "standard", "azure": "hot"}[cloud]
