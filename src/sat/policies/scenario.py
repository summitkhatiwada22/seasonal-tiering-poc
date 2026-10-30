"""What a storage policy sees: the objects, their read history and the simulated window.

A ``Scenario`` holds the whole read history from the first day of data (``hist_start``) and a
window to simulate: ``sim_start`` (absolute day index) and ``n_days``. The first part of the window
is a warm-up so every policy reaches its steady state; costs and waits are measured from
``measure_from`` (relative to the window). Policies may look at reads *before* a day to decide
that day (causal); only the oracle reference looks ahead, and it is labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import cached_property

import numpy as np
import numpy.typing as npt

from sat.prices import PriceSheet
from sat.sim import Inventory, SimResult
from sat.sim.rules import BYTES_PER_GB, BYTES_PER_KB

IntArray = npt.NDArray[np.int64]
Int32Array = npt.NDArray[np.int32]
FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

SMALL_OBJECT_BYTES = 128 * BYTES_PER_KB  # AWS lifecycle default: smaller objects never transition
LOG_BYTES_PER_READ = 500  # assumed size of one raw access-log record (AWS, Google), kept one day
COUNT_BYTES_PER_OBJECT_DAY = 16  # daily read count kept per object and day with reads
COUNT_RETENTION_MONTHS = 24
DAYS_PER_MONTH = 30.4375
LAG = 364  # weekday-aligned "same day last year"
MAX_AHEAD = LAG - 1  # last year's reads can look this far ahead without seeing today
LOOKBACK = 366  # history kept before the window for recency signals


@dataclass(frozen=True)
class Scenario:
    dataset: str
    sheet: PriceSheet
    sizes: IntArray  # bytes per object
    reads: IntArray  # (objects, history days), integer reads per day from hist_start
    created: IntArray  # absolute day each object is first stored (its first demand day)
    hist_start: date
    sim_start: int  # absolute index of the first simulated day
    n_days: int
    measure_from: int  # window-relative day where measurement starts
    restore_time: str = "high"
    count: FloatArray | None = None  # identical objects per row (None = 1)

    def __post_init__(self) -> None:
        n = len(self.sizes)
        if self.reads.shape[0] != n or self.created.shape != (n,):
            raise ValueError("sizes, reads and created must have one row per object")
        if self.sim_start < 0 or self.sim_start + self.n_days > self.reads.shape[1]:
            raise ValueError("the window must lie inside the read history")
        if not 0 <= self.measure_from < self.n_days:
            raise ValueError("measure_from must be inside the window")
        if (self.created >= self.sim_start + self.n_days).any():
            raise ValueError("every object must exist by the end of the window")

    # ---------------------------------------------------------------- views

    @property
    def n_objects(self) -> int:
        return len(self.sizes)

    @property
    def window_start(self) -> date:
        return self.hist_start + timedelta(days=self.sim_start)

    @property
    def end(self) -> int:
        return self.sim_start + self.n_days

    def window_reads(self) -> IntArray:
        return self.reads[:, self.sim_start : self.end]

    def created_rel(self) -> IntArray:
        """Creation day relative to the window (0 = stored when the window starts)."""
        return np.maximum(self.created - self.sim_start, 0)

    def inventory(self) -> Inventory:
        return Inventory(self.sizes, self.count, self.created_rel())

    def weight(self) -> FloatArray:
        return np.ones(self.n_objects) if self.count is None else self.count

    def small(self) -> BoolArray:
        return self.sizes < SMALL_OBJECT_BYTES

    def tier_index(self, name: str) -> int:
        return self.sheet.tier_order.index(name)

    def min_days(self, tier: str) -> int:
        return int(self.sheet.get(tier, "min_storage_days"))

    def initial_idle_days(self) -> IntArray:
        """Full days without a read before the window, counting creation as an access."""
        before = self.reads[:, : self.sim_start] > 0
        last_read = np.full(self.n_objects, -(10**6), dtype=np.int64)
        if self.sim_start > 0:
            any_read = before.any(axis=1)
            from_end = np.argmax(before[:, ::-1], axis=1)
            last_read = np.where(any_read, self.sim_start - 1 - from_end, last_read)
        last = np.maximum(last_read, self.created - 1)
        idle: IntArray = np.maximum(self.sim_start - last - 1, 0).astype(np.int64)
        return idle

    def with_window(self, sim_start: int, n_days: int, measure_from: int) -> Scenario:
        return replace(self, sim_start=sim_start, n_days=n_days, measure_from=measure_from)

    # ---------------------------------------------------------------- policy's own costs

    def observation_charge(self, result: SimResult, per_object_day: bool) -> None:
        """Add the cost of knowing when objects are read, for policies that need it.

        Azure (``per_object_day``): last-access-time tracking, one "other operation" per object per
        day with a read. AWS and Google (assumption A12): server access logs, free to enable but
        stored in the first class; each raw record (``LOG_BYTES_PER_READ``) is kept one day and
        folded into a daily count per object (``COUNT_BYTES_PER_OBJECT_DAY``) kept
        ``COUNT_RETENTION_MONTHS`` months, all charged on the read day. The compute that folds
        the logs is not counted.
        """
        reads = self.window_reads().astype(np.float64)
        if per_object_day:
            fee = float(self.sheet.extras["other_operations_per_1000"].value) / 1000
            each = (reads > 0) * fee
        else:
            hot = self.sheet.tier_order[0]
            price = self.sheet.get(hot, "storage_usd_per_gb_month")
            raw = reads * (LOG_BYTES_PER_READ / BYTES_PER_GB) * price / DAYS_PER_MONTH
            counts = (reads > 0) * (COUNT_BYTES_PER_OBJECT_DAY / BYTES_PER_GB) * price
            each = raw + counts * COUNT_RETENTION_MONTHS
        result.add_charge("monitoring", each * self.weight()[:, None])

    # ---------------------------------------------------------------- signals (cached)

    @cached_property
    def _base(self) -> int:
        return max(0, self.sim_start - LOOKBACK)

    @cached_property
    def _read_cs(self) -> Int32Array:
        """Cumulative count of read days from ``_base`` to the window end (leading zero)."""
        read = self.reads[:, self._base : self.end] > 0
        cs = np.zeros((self.n_objects, read.shape[1] + 1), dtype=np.int32)
        np.cumsum(read, axis=1, out=cs[:, 1:])
        return cs

    @cached_property
    def _pred_cs(self) -> Int32Array:
        """Same for last year's reads shifted by LAG days, from ``_base`` to the window end plus
        MAX_AHEAD days (all of it known before the window ends)."""
        lo, hi = self._base - LAG, self.end + MAX_AHEAD - LAG
        pred = np.zeros((self.n_objects, hi - lo), dtype=bool)
        src_lo = max(lo, 0)
        pred[:, src_lo - lo :] = self.reads[:, src_lo:hi] > 0
        cs = np.zeros((self.n_objects, pred.shape[1] + 1), dtype=np.int32)
        np.cumsum(pred, axis=1, out=cs[:, 1:])
        return cs

    def _any(self, cs: Int32Array, lo: int, hi: int) -> BoolArray:
        if hi < lo:
            return np.zeros((self.n_objects, self.n_days), dtype=bool)
        width = cs.shape[1] - 1
        a = self.sim_start - self._base + np.arange(self.n_days)
        start = np.clip(a + lo, 0, width)
        stop = np.clip(a + hi + 1, 0, width)
        out: BoolArray = (cs[:, stop] - cs[:, start]) > 0
        return out

    @cached_property
    def _count_cs(self) -> IntArray:
        """Cumulative read counts from ``_base`` to the window end (leading zero)."""
        reads = self.reads[:, self._base : self.end]
        cs = np.zeros((self.n_objects, reads.shape[1] + 1), dtype=np.int64)
        np.cumsum(reads, axis=1, out=cs[:, 1:])
        return cs

    @cached_property
    def _pred_count_cs(self) -> IntArray:
        """Cumulative counts of last year's reads (shifted by LAG), like ``_pred_cs``."""
        lo, hi = self._base - LAG, self.end + MAX_AHEAD - LAG
        pred = np.zeros((self.n_objects, hi - lo), dtype=np.int64)
        src_lo = max(lo, 0)
        pred[:, src_lo - lo :] = self.reads[:, src_lo:hi]
        cs = np.zeros((self.n_objects, pred.shape[1] + 1), dtype=np.int64)
        np.cumsum(pred, axis=1, out=cs[:, 1:])
        return cs

    def _sum(self, cs: IntArray | Int32Array, lo: int, hi: int) -> IntArray:
        if hi < lo:
            return np.zeros((self.n_objects, self.n_days), dtype=np.int64)
        width = cs.shape[1] - 1
        a = self.sim_start - self._base + np.arange(self.n_days)
        start = np.clip(a + lo, 0, width)
        stop = np.clip(a + hi + 1, 0, width)
        out: IntArray = (cs[:, stop] - cs[:, start]).astype(np.int64)
        return out

    def reads_sum(self, lo: int, hi: int) -> IntArray:
        """``[i, w]``: reads of object i on days w+lo .. w+hi (unknown future days count 0)."""
        return self._sum(self._count_cs, lo, hi)

    def read_days_sum(self, lo: int, hi: int) -> IntArray:
        """``[i, w]``: number of days with a read among w+lo .. w+hi."""
        return self._sum(self._read_cs, lo, hi)

    def last_year_reads_sum(self, lo: int, hi: int) -> IntArray:
        if hi > MAX_AHEAD:
            raise ValueError(f"last year's reads can only look {MAX_AHEAD} days ahead")
        return self._sum(self._pred_count_cs, lo, hi)

    def last_year_read_days_sum(self, lo: int, hi: int) -> IntArray:
        if hi > MAX_AHEAD:
            raise ValueError(f"last year's reads can only look {MAX_AHEAD} days ahead")
        return self._sum(self._pred_cs, lo, hi)

    def read_within(self, lo: int, hi: int) -> BoolArray:
        """``[i, w]``: object i is read on some day from w+lo to w+hi (window days, inclusive).

        Days after the window end are unknown and count as no read."""
        return self._any(self._read_cs, lo, hi)

    def last_year_within(self, lo: int, hi: int) -> BoolArray:
        """``[i, w]``: object i was read LAG days before some day from w+lo to w+hi.

        ``hi`` must be at most MAX_AHEAD so the answer uses only reads before day w."""
        if hi > MAX_AHEAD:
            raise ValueError(f"last year's reads can only look {MAX_AHEAD} days ahead")
        return self._any(self._pred_cs, lo, hi)


# -------------------------------------------------------------------- matrix helpers


def any_in_window(flags: BoolArray, lo: int, hi: int) -> BoolArray:
    """``out[i, t]`` = any ``flags[i, t+lo .. t+hi]`` (inclusive, clipped to the matrix)."""
    if hi < lo:
        return np.zeros(flags.shape, dtype=bool)
    n, t = flags.shape
    cs = np.zeros((n, t + 1), dtype=np.int64)
    np.cumsum(flags, axis=1, out=cs[:, 1:])
    idx = np.arange(t)
    a = np.clip(idx + lo, 0, t)
    b = np.clip(idx + hi + 1, 0, t)
    out: BoolArray = (cs[:, b] - cs[:, a]) > 0
    return out


def runs(mask: BoolArray) -> list[tuple[int, int, int]]:
    """Maximal runs of True per row: (row, first, last), last inclusive."""
    n, t = mask.shape
    padded = np.zeros((n, t + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    diff = np.diff(padded, axis=1)
    rows_s, starts = np.nonzero(diff == 1)
    rows_e, ends = np.nonzero(diff == -1)
    order_s = np.lexsort((starts, rows_s))
    order_e = np.lexsort((ends, rows_e))
    return [
        (int(r), int(s), int(e) - 1)
        for r, s, e in zip(rows_s[order_s], starts[order_s], ends[order_e], strict=True)
    ]
