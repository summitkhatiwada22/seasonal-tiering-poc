"""Cost and waiting-time simulator for a plan made of ordinary storage classes.

The engine walks the days in order and, for every object at once (numpy arrays), applies the rules
in docs/SIM_RULES.md: class moves (M1-M3) with early deletion (E1-E4), restores of temporary copies
(T1-T6), reads (R1-R3), daily storage (S1-S3) and waits (W1-W2).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

import numpy as np
import numpy.typing as npt

from sat.prices import PriceSheet
from sat.sim.model import (
    COST_CATEGORIES,
    FloatArray,
    Inventory,
    Plan,
    Restore,
    SimConfig,
    SimResult,
    WaitStats,
    merge_results,
)
from sat.sim.rules import (
    BYTES_PER_GB,
    BYTES_PER_KB,
    CloudRules,
    daily_storage_factor,
    day_dates,
    early_delete_factor,
    is_archive,
    restore_hours,
    rules_for,
    tier_field,
)

NO_HOUR = -np.inf


class _Ledger:
    """Adds charges to the per-category daily totals and to each object row's total."""

    def __init__(
        self, n_days: int, n_objects: int, weight: FloatArray, measure_from: int = 0
    ) -> None:
        self.daily = {c: np.zeros(n_days) for c in COST_CATEGORIES}
        self.per_object = np.zeros(n_objects)
        self.per_object_measured = np.zeros(n_objects)
        self.weight = weight
        self.measure_from = measure_from

    def charge(self, category: str, day: int, ids: npt.NDArray[np.int64], each: FloatArray) -> None:
        """``each`` is the charge for ONE object of each row in ``ids`` (rows are unique)."""
        if len(ids) == 0:
            return
        amounts = np.broadcast_to(each, ids.shape) * self.weight[ids]
        self.daily[category][day] += float(amounts.sum())
        self.per_object[ids] += amounts
        if day >= self.measure_from:
            self.per_object_measured[ids] += amounts


class _Engine:
    def __init__(
        self,
        sheet: PriceSheet,
        inventory: Inventory,
        reads: npt.ArrayLike,
        plan: Plan,
        start: date,
        config: SimConfig,
    ) -> None:
        self.sheet, self.config, self.start = sheet, config, start
        self.rules: CloudRules = rules_for(sheet)
        self.names = list(sheet.tier_order)
        self.sizes = inventory.sizes()
        self.weight = inventory.counts()
        self.created = inventory.created()
        n = len(self.sizes)

        reads_arr = np.asarray(reads)
        if reads_arr.ndim != 2 or reads_arr.shape[0] != n:
            raise ValueError(f"reads must have shape (objects={n}, days)")
        if (reads_arr < 0).any():
            raise ValueError("reads must not be negative")
        self.n_days = reads_arr.shape[1]
        before = np.arange(self.n_days)[None, :] < self.created[:, None]
        if (reads_arr * before).any():
            raise ValueError("an object is read before its created_day")
        tier = np.asarray(plan.tier)
        if tier.shape != reads_arr.shape:
            raise ValueError(f"plan.tier shape {tier.shape} must match reads {reads_arr.shape}")
        if tier.min() < 0 or tier.max() >= len(self.names):
            raise ValueError("plan.tier holds an index outside the price sheet's tier_order")
        # day-major copies so each day is one contiguous row
        self.reads_by_day = np.ascontiguousarray(reads_arr.T, dtype=np.float64)
        self.tier_by_day = np.ascontiguousarray(tier.T, dtype=np.int64)

        self.dates = day_dates(start, self.n_days)
        self.factor = daily_storage_factor(self.rules, start, self.n_days)
        self._prepare_tiers()

        clock = np.broadcast_to(np.asarray(plan.initial_clock_days, dtype=np.float64), (n,))
        self.clock_start = np.where(self.created > 0, self.created, -clock).astype(np.float64)
        self.cur = self.tier_by_day[0].copy()
        self.readable_from = np.full(n, NO_HOUR)  # hour the current class's data becomes readable
        self.copy_ready = np.full(n, NO_HOUR)  # temporary copy: ready hour (NO_HOUR = none)
        self.copy_expire = np.full(n, NO_HOUR)
        self.restores = self._group_restores(plan.restores)

        self.ledger = _Ledger(self.n_days, n, self.weight, config.measure_from)
        self.waits = WaitStats()
        self.cold_by_object = np.zeros(n)

    # ------------------------------------------------------------------ setup

    def _prepare_tiers(self) -> None:
        sheet, rules, names = self.sheet, self.rules, self.names
        t_count = len(names)
        self.price = np.array([sheet.get(t, "storage_usd_per_gb_month") for t in names])
        self.min_days = np.array([sheet.get(t, "min_storage_days") for t in names])
        self.archive = np.array([is_archive(sheet, t) for t in names])
        self.retrieval = np.array([sheet.get(t, "retrieval_usd_per_gb") for t in names])
        self.read_fee = np.array([tier_field(sheet, t, rules.read_field) / 1000 for t in names])
        self.down_fee = np.array([tier_field(sheet, t, rules.down_fee_field) / 1000 for t in names])
        self.up_fee = np.array([tier_field(sheet, t, rules.up_fee_field) / 1000 for t in names])
        self.write_fee = np.array([tier_field(sheet, t, rules.write_field) / 1000 for t in names])
        min_bytes = np.array([sheet.get(t, "min_billable_object_kb") * BYTES_PER_KB for t in names])
        self.size_gb = self.sizes / BYTES_PER_GB
        billable_gb = np.maximum(self.sizes[None, :], min_bytes[:, None]) / BYTES_PER_GB
        self.storage_month = billable_gb * self.price[:, None]  # (tiers, objects)

        # S3: per-object overhead, split between this class's rate and another class's rate
        self.overhead_month = np.zeros(t_count)
        overhead_at_tier_gb = np.zeros(t_count)
        for i, name in enumerate(names):
            kb = sheet.get(name, "per_object_overhead_kb")
            if kb <= 0:
                continue
            other_kb = min(kb, rules.overhead_other_kb)
            at_tier_kb = kb - other_kb
            other_price = (
                sheet.get(rules.overhead_other_tier, "storage_usd_per_gb_month")
                if rules.overhead_other_tier
                else 0.0
            )
            overhead_at_tier_gb[i] = at_tier_kb * BYTES_PER_KB / BYTES_PER_GB
            self.overhead_month[i] = (
                (at_tier_kb * self.price[i] + other_kb * other_price) * BYTES_PER_KB / BYTES_PER_GB
            )
        # E2: early deletion is on the bytes billed at the class's own rate
        self.early_gb = billable_gb + overhead_at_tier_gb[:, None]

        self.copy_price = (
            sheet.get(rules.copy_tier, "storage_usd_per_gb_month") if rules.copy_tier else 0.0
        )
        self.copy_write_fee = (
            tier_field(sheet, rules.copy_tier, rules.copy_write_field) / 1000
            if rules.copy_tier and rules.copy_write_field
            else 0.0
        )
        if self.config.include_egress:
            self.egress = sheet.extras["egress_usd_per_gb_first_tier"].value
        else:
            self.egress = 0.0

    def _group_restores(self, orders: Sequence[Restore]) -> dict[int, list[Restore]]:
        grouped: dict[int, list[Restore]] = defaultdict(list)
        n = len(self.sizes)
        for order in orders:
            if not isinstance(order, Restore):
                raise TypeError("plan.restores must hold Restore objects")
            if not 0 <= order.obj < n or not 0 <= order.day < self.n_days:
                raise ValueError(f"restore out of range: {order}")
            if order.keep_days < 1:
                raise ValueError(f"restore keep_days must be at least 1: {order}")
            grouped[order.day].append(order)
        return grouped

    # ------------------------------------------------------------------ helpers

    def _restore_terms(self, tier: int, speed: str) -> tuple[float, float, float]:
        """(request fee, retrieval per GB, hours) for restoring from archive class ``tier``."""
        rules, name = self.rules, self.names[tier]
        if speed not in rules.restore_fee_by_speed:
            raise ValueError(f"{rules.cloud}: unknown restore speed {speed!r}")
        hours = restore_hours(self.sheet, rules, name, speed, self.config.restore_time)
        fee = tier_field(self.sheet, name, rules.restore_fee_by_speed[speed]) / 1000
        per_gb = tier_field(self.sheet, name, rules.retrieval_by_speed[speed])
        return fee, per_gb, hours

    def _start_copies(
        self, day: int, ids: npt.NDArray[np.int64], keep_days: npt.NDArray[np.float64], speed: str
    ) -> None:
        """New temporary copies for archived objects ``ids`` (none may hold a copy)."""
        hour0 = 24.0 * day
        for tier in np.unique(self.cur[ids]):
            sel = ids[self.cur[ids] == tier]
            keep = keep_days[self.cur[ids] == tier]
            fee, per_gb, hours = self._restore_terms(int(tier), speed)
            ready = hour0 + hours
            expire = np.ceil((ready + 24.0 * keep) / 24.0 - 1e-9) * 24.0  # T3
            self.ledger.charge("restore_requests", day, sel, np.full(len(sel), fee))
            if self.copy_write_fee:
                self.ledger.charge(
                    "restore_requests", day, sel, np.full(len(sel), self.copy_write_fee)
                )
            self.ledger.charge("retrieval", day, sel, self.size_gb[sel] * per_gb)
            self._charge_copy_hours(day, sel, expire - ready)
            self.copy_ready[sel] = ready
            self.copy_expire[sel] = expire

    def _charge_copy_hours(
        self, day: int, ids: npt.NDArray[np.int64], hours: FloatArray | float
    ) -> None:
        each = self.size_gb[ids] * self.copy_price * np.asarray(hours) / 24.0 * self.factor[day]
        self.ledger.charge("copy_storage", day, ids, each)

    # ------------------------------------------------------------------ daily steps

    def _move(self, day: int) -> None:
        new = self.tier_by_day[day]
        moved = np.flatnonzero((new != self.cur) & (self.created < day))
        if len(moved) == 0:
            return
        hour0 = 24.0 * day
        leave_factor = early_delete_factor(self.rules, self.dates[day])
        pairs = self.cur[moved] * len(self.names) + new[moved]
        for pair in np.unique(pairs):
            ids = moved[pairs == pair]
            src, dst = divmod(int(pair), len(self.names))
            down = dst > src
            keeps_clock = down and self.rules.lifecycle_keeps_clock
            if self.min_days[src] > 0 and not keeps_clock:
                clock = day - self.clock_start[ids]
                remaining = np.maximum(0.0, self.min_days[src] - clock)
                each = remaining * self.price[src] * self.early_gb[src, ids] * leave_factor
                self.ledger.charge("early_delete", day, ids, each)
            if down:
                self.ledger.charge("transition", day, ids, np.full(len(ids), self.down_fee[dst]))
            elif self.archive[src]:
                self._move_up_from_archive(day, ids, src, dst)
            else:
                fee = self.up_fee[dst] if self.rules.up_fee_on == "dest" else self.up_fee[src]
                self.ledger.charge("transition", day, ids, np.full(len(ids), fee))
                self.ledger.charge("retrieval", day, ids, self.size_gb[ids] * self.retrieval[src])
                self.readable_from[ids] = np.maximum(self.readable_from[ids], hour0)
            if not keeps_clock:
                self.clock_start[ids] = day
            self.cur[ids] = dst
            self.copy_ready[ids] = NO_HOUR
            self.copy_expire[ids] = NO_HOUR

    def _move_up_from_archive(
        self, day: int, ids: npt.NDArray[np.int64], src: int, dst: int
    ) -> None:
        hour0 = 24.0 * day
        speed = self.config.up_move_speed
        fee, per_gb, hours = self._restore_terms(src, speed)
        if self.rules.up_fee_on == "source":  # Azure: Set Blob Tier rehydration (M3)
            self.ledger.charge("transition", day, ids, np.full(len(ids), fee))
            self.ledger.charge("retrieval", day, ids, self.size_gb[ids] * per_gb)
            self.readable_from[ids] = hour0 + hours
            return
        # AWS: restore (unless a copy already exists), then COPY into the new class (M3)
        has_copy = self.copy_expire[ids] > hour0
        need = ids[~has_copy]
        if len(need):
            self.ledger.charge("restore_requests", day, need, np.full(len(need), fee))
            self.ledger.charge("retrieval", day, need, self.size_gb[need] * per_gb)
            ready = hour0 + hours
            expire = np.ceil((ready + 24.0) / 24.0 - 1e-9) * 24.0  # restore with Days = 1
            self._charge_copy_hours(day, need, expire - ready)
            self.readable_from[need] = ready
        kept = ids[has_copy]
        self.readable_from[kept] = np.maximum(self.copy_ready[kept], hour0)
        self.ledger.charge("transition", day, ids, np.full(len(ids), self.up_fee[dst]))

    def _planned_restores(self, day: int) -> None:
        orders = self.restores.get(day)
        if not orders:
            return
        keep_by_obj: dict[tuple[int, str], int] = {}
        for o in orders:
            key = (o.obj, o.speed)
            keep_by_obj[key] = max(keep_by_obj.get(key, 0), o.keep_days)
        hour0 = 24.0 * day
        for speed in sorted({s for _, s in keep_by_obj}):
            ids = np.array([obj for (obj, s) in keep_by_obj if s == speed], dtype=np.int64)
            keep = np.array([keep_by_obj[(obj, speed)] for obj in ids], dtype=np.float64)
            if (self.created[ids] > day).any():
                raise ValueError(f"day {day}: restore asked for objects not yet created")
            if not self.archive[self.cur[ids]].all():
                bad = ids[~self.archive[self.cur[ids]]]
                raise ValueError(f"day {day}: restore asked for objects not archived: {bad[:5]}")
            pending = (self.copy_ready > hour0)[ids]
            active = ((self.copy_ready <= hour0) & (self.copy_expire > hour0))[ids]
            fresh = ~pending & ~active
            self._start_copies(day, ids[fresh], keep[fresh], speed)
            again, again_keep = ids[active], keep[active]
            if len(again):  # T4: extend the existing copy
                new_expire = hour0 + 24.0 * again_keep
                extra = np.maximum(0.0, new_expire - self.copy_expire[again])
                if self.rules.reissue_costs_a_read:
                    fees = self.read_fee[self.cur[again]]
                    self.ledger.charge("restore_requests", day, again, fees)
                self._charge_copy_hours(day, again, extra)
                self.copy_expire[again] = np.maximum(self.copy_expire[again], new_expire)
            # pending restores: a second request while one is in progress changes nothing

    def _reads(self, day: int) -> None:
        counts = self.reads_by_day[day]
        ids = np.flatnonzero(counts)
        if len(ids) == 0:
            return
        hour0 = 24.0 * day
        c = counts[ids]
        measured = day >= self.config.measure_from
        if measured:
            self.waits.reads += float((c * self.weight[ids]).sum())
        tiers = self.cur[ids]
        archived = self.archive[tiers]

        # archived objects: use the copy, wait for a pending one, or restore on demand (R2)
        arch = ids[archived]
        if len(arch):
            none = self.copy_expire[arch] <= hour0
            if none.any():
                need = arch[none]
                keep = np.full(len(need), float(self.config.on_demand_keep_days))
                self._start_copies(day, need, keep, self.config.on_demand_speed)
            wait = np.maximum(0.0, self.copy_ready[arch] - hour0)
            ca = counts[arch]
            if self.rules.copy_read_on_archive:
                fee = self.read_fee[self.cur[arch]]
            else:
                fee = np.full(len(arch), self.read_fee[self.names.index(self.rules.copy_tier)])  # type: ignore[arg-type]
            self.ledger.charge("read_requests", day, arch, ca * fee)
            if measured:
                self.waits.add(wait, ca, self.weight[arch])
                self.cold_by_object[arch] += ca * self.weight[arch] * (wait > 0)

        online = ids[~archived]
        if len(online):
            co = counts[online]
            t = self.cur[online]
            self.ledger.charge("read_requests", day, online, co * self.read_fee[t])
            self.ledger.charge(
                "retrieval", day, online, co * self.size_gb[online] * self.retrieval[t]
            )
            wait = np.maximum(0.0, self.readable_from[online] - hour0)
            if measured:
                self.waits.add(wait, co, self.weight[online])
                self.cold_by_object[online] += co * self.weight[online] * (wait > 0)

        if self.egress:
            self.ledger.charge("egress", day, ids, c * self.size_gb[ids] * self.egress)

    def _create(self, day: int) -> None:
        ids = np.flatnonzero(self.created == day)
        if day == 0 or len(ids) == 0:
            return
        self.cur[ids] = self.tier_by_day[day][ids]
        self.clock_start[ids] = day
        self.ledger.charge("write_requests", day, ids, self.write_fee[self.cur[ids]])

    def _storage(self, day: int) -> None:
        ids = np.flatnonzero(self.created <= day)
        f = self.factor[day]
        self.ledger.charge("storage", day, ids, self.storage_month[self.cur[ids], ids] * f)
        if self.overhead_month.any():
            self.ledger.charge("overhead_storage", day, ids, self.overhead_month[self.cur[ids]] * f)

    # ------------------------------------------------------------------ run

    def run(self) -> SimResult:
        for day in range(self.n_days):
            self._create(day)
            if day > 0:
                self._move(day)
            self._planned_restores(day)
            self._reads(day)
            self._storage(day)
        costs = {c: float(v.sum()) for c, v in self.ledger.daily.items()}
        return SimResult(
            cloud=self.sheet.cloud,
            costs=costs,
            daily=self.ledger.daily,
            per_object=self.ledger.per_object,
            waits=self.waits,
            measure_from=self.config.measure_from,
            per_object_measured=self.ledger.per_object_measured,
            cold_by_object=self.cold_by_object,
        )


def simulate(
    sheet: PriceSheet,
    inventory: Inventory,
    reads: npt.ArrayLike,
    plan: Plan,
    start: date,
    config: SimConfig | None = None,
) -> SimResult:
    """Bill and waits for ``plan`` over ``reads`` (shape objects x days), starting on ``start``."""
    return _Engine(sheet, inventory, reads, plan, start, config or SimConfig()).run()


def simulate_chunked(
    sheet: PriceSheet,
    inventory: Inventory,
    reads: npt.ArrayLike,
    plan: Plan,
    start: date,
    config: SimConfig | None = None,
    chunk_objects: int = 50_000,
) -> SimResult:
    """``simulate`` over groups of at most ``chunk_objects`` object rows, merged exactly.

    Objects never interact, so the result equals one run over all objects; memory stays bounded
    for large inventories (for example the synthetic L scale of 1 million objects)."""
    if chunk_objects < 1:
        raise ValueError("chunk_objects must be at least 1")
    sizes, counts, created = inventory.sizes(), inventory.counts(), inventory.created()
    reads_arr, tier = np.asarray(reads), np.asarray(plan.tier)
    clock = np.broadcast_to(np.asarray(plan.initial_clock_days, dtype=np.float64), sizes.shape)
    by_obj: dict[int, list[Restore]] = defaultdict(list)
    for order in plan.restores:
        by_obj[order.obj].append(order)
    parts = []
    for lo in range(0, len(sizes), chunk_objects):
        hi = min(lo + chunk_objects, len(sizes))
        restores = [
            Restore(o.obj - lo, o.day, o.keep_days, o.speed)
            for obj in range(lo, hi)
            for o in by_obj.get(obj, [])
        ]
        part_inv = Inventory(sizes[lo:hi], counts[lo:hi], created[lo:hi])
        part_plan = Plan(tier[lo:hi], restores, clock[lo:hi])
        parts.append(simulate(sheet, part_inv, reads_arr[lo:hi], part_plan, start, config))
    return merge_results(parts)
