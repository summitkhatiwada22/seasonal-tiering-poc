"""Inputs and outputs of the simulator."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]

COST_CATEGORIES: tuple[str, ...] = (
    "storage",  # object bytes at the class rate (after minimum billable size)
    "overhead_storage",  # per-object archive metadata (AWS 40 KB, Azure 8 KB)
    "copy_storage",  # temporary restored copies (AWS Standard rate, Azure Hot)
    "early_delete",  # minimum storage duration charges
    "transition",  # requests that change an object's class (lifecycle, copy, rewrite, set tier)
    "retrieval",  # per-GB retrieval fees (reads, restores, moves out of a class)
    "restore_requests",  # per-request restore fees (and Azure copy writes)
    "read_requests",  # GET / Class B / read operations
    "write_requests",  # uploads of objects created during the simulated period
    "monitoring",  # Intelligent-Tiering monitoring, Autoclass management fee
    "egress",  # internet transfer out (off by default)
)


@dataclass(frozen=True)
class Inventory:
    """The stored objects. Row *i* stands for ``count[i]`` identical objects of ``size_bytes[i]``.

    ``created_day[i]`` is the simulated day the object is uploaded (0 or less = already stored
    when the simulation starts). Nothing is billed for an object before it exists; on its creation
    day it is uploaded into the class the plan gives for that day (one write request).
    """

    size_bytes: npt.ArrayLike
    count: npt.ArrayLike | None = None
    created_day: npt.ArrayLike | None = None

    def created(self) -> IntArray:
        n = len(self.sizes())
        if self.created_day is None:
            return np.zeros(n, dtype=np.int64)
        created = np.asarray(self.created_day, dtype=np.int64)
        if created.shape != (n,):
            raise ValueError("created_day must have one value per object row")
        return np.maximum(created, 0)

    def sizes(self) -> IntArray:
        sizes = np.asarray(self.size_bytes, dtype=np.int64)
        if sizes.ndim != 1 or len(sizes) == 0:
            raise ValueError("size_bytes must be a non-empty 1-D array")
        if (sizes <= 0).any():
            raise ValueError("every object size must be positive")
        return sizes

    def counts(self) -> FloatArray:
        n = len(self.sizes())
        if self.count is None:
            return np.ones(n, dtype=np.float64)
        counts = np.asarray(self.count, dtype=np.float64)
        if counts.shape != (n,) or (counts <= 0).any():
            raise ValueError("count must be positive, one per object row")
        return counts


@dataclass(frozen=True)
class Restore:
    """Ask for a temporary readable copy of an archived object (pre-warming).

    ``day`` is the simulated day the request is made (at 00:00). ``keep_days`` is the Days value of
    the request. ``speed`` is ``standard``, ``bulk`` or ``expedited`` (AWS) or ``standard`` /
    ``high`` (Azure).
    """

    obj: int
    day: int
    keep_days: int
    speed: str = "standard"


@dataclass(frozen=True)
class Plan:
    """What a storage policy decided.

    ``tier[i, d]`` is the index (in the price sheet's ``tier_order``) of the class object *i* is in
    on day *d*. A change from day *d-1* to *d* is a move made at 00:00 on day *d*.
    ``initial_clock_days`` is how many days each object has already counted towards its class's
    minimum storage duration before day 0 (default: long past every minimum).
    """

    tier: npt.ArrayLike
    restores: Sequence[Restore] = ()
    initial_clock_days: npt.ArrayLike | int = 10**6


@dataclass(frozen=True)
class SimConfig:
    """Settings that are not part of a policy's decisions."""

    restore_time: str = "high"  # "high" or "low" end of each provider's stated restore time
    on_demand_speed: str = "standard"  # speed of restores triggered by a read of an archived object
    on_demand_keep_days: int = 1
    up_move_speed: str = "standard"  # speed of the restore behind a move up out of an archive class
    include_egress: bool = False
    measure_from: int = 0  # reads and waits are counted from this day on (earlier days = warm-up)

    def __post_init__(self) -> None:
        if self.restore_time not in {"high", "low"}:
            raise ValueError("restore_time must be 'high' or 'low'")
        if self.on_demand_keep_days < 1:
            raise ValueError("on_demand_keep_days must be at least 1")
        if self.measure_from < 0:
            raise ValueError("measure_from must not be negative")


@dataclass
class WaitStats:
    """Reads that found their object not yet readable, and how long they waited.

    ``hours_all_reads`` assumes every read that day waited (upper bound); ``hours_first_read``
    counts one wait per object-day (lower bound). ``histogram`` maps wait hours to read counts.
    """

    reads: float = 0.0
    cold_reads: float = 0.0
    cold_object_days: float = 0.0
    hours_all_reads: float = 0.0
    hours_first_read: float = 0.0
    max_hours: float = 0.0
    histogram: dict[float, float] = field(default_factory=dict)

    def add(self, hours: FloatArray, reads: FloatArray, weight: FloatArray) -> None:
        """Record waits: one entry per object row (reads per object x number of objects)."""
        waited = hours > 0
        if not waited.any():
            return
        h, r, w = hours[waited], reads[waited], weight[waited]
        self.cold_reads += float((r * w).sum())
        self.cold_object_days += float(w.sum())
        self.hours_all_reads += float((h * r * w).sum())
        self.hours_first_read += float((h * w).sum())
        self.max_hours = max(self.max_hours, float(h.max()))
        for value in np.unique(h):
            mask = h == value
            key = round(float(value), 6)
            self.histogram[key] = self.histogram.get(key, 0.0) + float((r[mask] * w[mask]).sum())

    def merge(self, other: WaitStats) -> None:
        """Add another set of waits (for example another chunk of objects) to this one."""
        self.reads += other.reads
        self.cold_reads += other.cold_reads
        self.cold_object_days += other.cold_object_days
        self.hours_all_reads += other.hours_all_reads
        self.hours_first_read += other.hours_first_read
        self.max_hours = max(self.max_hours, other.max_hours)
        for hours, count in other.histogram.items():
            self.histogram[hours] = self.histogram.get(hours, 0.0) + count

    def share_waited(self) -> float:
        return self.cold_reads / self.reads if self.reads else 0.0

    def percentile_hours(self, q: float) -> float:
        """Wait (hours) at percentile ``q`` (0-100) over ALL reads, zero-wait reads included."""
        if self.reads == 0:
            return 0.0
        waits = sorted(self.histogram.items())
        zero = self.reads - self.cold_reads
        target = q / 100 * self.reads
        if target <= zero:
            return 0.0
        running = zero
        for hours, count in waits:
            running += count
            if running >= target - 1e-9:
                return hours
        return waits[-1][0]


@dataclass
class SimResult:
    """The bill (USD) by category, by day and by object row, plus the waits.

    ``per_object_measured`` and ``cold_by_object`` cover only days from ``measure_from`` on: each
    object row's cost and its reads that waited (weighted by the row's count).
    ``wait_hours_by_object`` adds up the hours those reads waited (every read that day counted, as
    ``hours_all_reads``) and ``max_wait_by_object`` is each row's longest wait."""

    cloud: str
    costs: dict[str, float]
    daily: dict[str, FloatArray]
    per_object: FloatArray
    waits: WaitStats
    measure_from: int = 0
    per_object_measured: FloatArray | None = None
    cold_by_object: FloatArray | None = None
    wait_hours_by_object: FloatArray | None = None  # measured hours waited, summed over reads
    max_wait_by_object: FloatArray | None = None  # longest measured wait (hours), per object row

    @property
    def total(self) -> float:
        return float(sum(self.costs.values()))

    def costs_from(self, day: int) -> dict[str, float]:
        """Cost by category for days ``day`` onwards (drop a warm-up period)."""
        return {c: float(v[day:].sum()) for c, v in self.daily.items()}

    def total_from(self, day: int) -> float:
        return float(sum(self.costs_from(day).values()))

    def add_charge(self, category: str, by_object_day: FloatArray) -> None:
        """Add a charge the simulator does not compute itself (for example a policy's own
        monitoring cost), given per object row and day (already weighted by the row's count)."""
        n_days = len(self.daily[category])
        if by_object_day.shape != (len(self.per_object), n_days):
            raise ValueError("charge must be an (object rows x days) array")
        self.daily[category] = self.daily[category] + by_object_day.sum(axis=0)
        self.per_object = self.per_object + by_object_day.sum(axis=1)
        if self.per_object_measured is not None:
            measured = by_object_day[:, self.measure_from :].sum(axis=1)
            self.per_object_measured = self.per_object_measured + measured
        self.costs[category] = float(self.daily[category].sum())

    def monthly(self, start_ordinal: int) -> dict[tuple[int, int], float]:
        """Total cost per calendar (year, month); ``start_ordinal`` = ``start.toordinal()``."""
        from datetime import date

        out: dict[tuple[int, int], float] = {}
        total = sum(self.daily.values())
        for offset, value in enumerate(np.asarray(total)):
            day = date.fromordinal(start_ordinal + offset)
            key = (day.year, day.month)
            out[key] = out.get(key, 0.0) + float(value)
        return out


def merge_results(parts: Sequence[SimResult]) -> SimResult:
    """Combine runs over disjoint groups of objects (chunks) into one result.

    Objects never interact in the simulator, so running chunks separately and merging is exact:
    costs and daily totals add up, per-object rows are concatenated in order and waits merge.
    """
    if not parts:
        raise ValueError("nothing to merge")
    first = parts[0]
    if any(p.cloud != first.cloud for p in parts):
        raise ValueError("cannot merge results from different clouds")
    if any(p.measure_from != first.measure_from for p in parts):
        raise ValueError("cannot merge results with different measurement windows")
    daily = {c: np.sum([p.daily[c] for p in parts], axis=0) for c in first.daily}
    waits = WaitStats()
    for p in parts:
        waits.merge(p.waits)

    def joined(name: str) -> FloatArray | None:
        arrays = [getattr(p, name) for p in parts]
        return None if any(a is None for a in arrays) else np.concatenate(arrays)

    return SimResult(
        cloud=first.cloud,
        costs={c: float(v.sum()) for c, v in daily.items()},
        daily=daily,
        per_object=np.concatenate([p.per_object for p in parts]),
        waits=waits,
        measure_from=first.measure_from,
        per_object_measured=joined("per_object_measured"),
        cold_by_object=joined("cold_by_object"),
        wait_hours_by_object=joined("wait_hours_by_object"),
        max_wait_by_object=joined("max_wait_by_object"),
    )
