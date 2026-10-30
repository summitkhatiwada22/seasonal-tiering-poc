"""Billing of the providers' own automatic tiering: S3 Intelligent-Tiering and GCS Autoclass.

Both move each object by the number of whole days since it was last read (rules I1-I4 in
docs/SIM_RULES.md). An object last read on day L has ``d - L - 1`` full days without access at the
start of day d; ``initial_idle_days`` sets that number for day 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from sat.prices import PriceSheet
from sat.sim.engine import _Ledger
from sat.sim.model import Inventory, SimResult, WaitStats
from sat.sim.rules import BYTES_PER_GB, BYTES_PER_KB, daily_storage_factor, rules_for


@dataclass(frozen=True)
class ITConfig:
    """Optional archive tiers of S3 Intelligent-Tiering (None = not activated)."""

    archive_access_days: int | None = None  # 90..730
    deep_archive_access_days: int | None = None  # 180..730

    def __post_init__(self) -> None:
        aa, da = self.archive_access_days, self.deep_archive_access_days
        if aa is not None and not 90 <= aa <= 730:
            raise ValueError("archive_access_days must be between 90 and 730")
        if da is not None and not 180 <= da <= 730:
            raise ValueError("deep_archive_access_days must be between 180 and 730")
        if aa is not None and da is not None and da <= aa:
            raise ValueError("deep_archive_access_days must exceed archive_access_days")


@dataclass(frozen=True)
class _Prepared:
    sizes: npt.NDArray[np.int64]
    weight: npt.NDArray[np.float64]
    created: npt.NDArray[np.int64]
    reads_by_day: npt.NDArray[np.float64]
    last: npt.NDArray[np.float64]


def _prepare(
    inventory: Inventory, reads: npt.ArrayLike, initial_idle_days: npt.ArrayLike | int
) -> _Prepared:
    sizes, weight, created = inventory.sizes(), inventory.counts(), inventory.created()
    arr = np.asarray(reads)
    if arr.ndim != 2 or arr.shape[0] != len(sizes):
        raise ValueError(f"reads must have shape (objects={len(sizes)}, days)")
    if (arr < 0).any():
        raise ValueError("reads must not be negative")
    if (arr * (np.arange(arr.shape[1])[None, :] < created[:, None])).any():
        raise ValueError("an object is read before its created_day")
    idle = np.broadcast_to(np.asarray(initial_idle_days, dtype=np.float64), sizes.shape)
    # day of the last read before day 0; a new object counts as read the day before its upload
    last = np.where(created > 0, created - 1.0, -1.0 - idle)
    return _Prepared(sizes, weight, created, np.ascontiguousarray(arr.T, dtype=np.float64), last)


def simulate_intelligent_tiering(
    sheet: PriceSheet,
    inventory: Inventory,
    reads: npt.ArrayLike,
    start: date,
    config: ITConfig | None = None,
    initial_idle_days: npt.ArrayLike | int = 0,
    restore_time: str = "high",
) -> SimResult:
    if sheet.cloud != "aws":
        raise ValueError("S3 Intelligent-Tiering needs the AWS price sheet")
    cfg = config or ITConfig()
    x = {k: p.value for k, p in sheet.extras.items()}
    prep = _prepare(inventory, reads, initial_idle_days)
    sizes, weight, created, reads_by_day, last = (
        prep.sizes,
        prep.weight,
        prep.created,
        prep.reads_by_day,
        prep.last.copy(),
    )
    n, n_days = len(sizes), reads_by_day.shape[0]
    factor = daily_storage_factor(rules_for(sheet), start, n_days)

    # tiers: 0 Frequent, 1 Infrequent, 2 Archive Instant, 3 Archive Access, 4 Deep Archive Access
    price = np.array(
        [
            x["intelligent_tiering_frequent_usd_per_gb_month"],
            x["intelligent_tiering_infrequent_usd_per_gb_month"],
            x["intelligent_tiering_archive_instant_usd_per_gb_month"],
            x["intelligent_tiering_archive_access_usd_per_gb_month"],
            x["intelligent_tiering_deep_archive_access_usd_per_gb_month"],
        ]
    )
    overhead_kb = x["intelligent_tiering_archive_overhead_kb"]
    other_kb = 8.0  # 8 KB of each archived object's overhead is billed at the Standard rate
    standard_price = sheet.get("standard", "storage_usd_per_gb_month")
    overhead_month = np.zeros(5)
    for t in (3, 4):
        overhead_month[t] = (
            ((overhead_kb - other_kb) * price[t] + other_kb * standard_price)
            * BYTES_PER_KB
            / BYTES_PER_GB
        )
    suffix = "_low" if restore_time == "low" else ""
    if restore_time not in {"high", "low"}:
        raise ValueError("restore_time must be 'high' or 'low'")
    aa_hours = x.get(
        "intelligent_tiering_archive_access_restore_hours" + suffix,
        x["intelligent_tiering_archive_access_restore_hours"],
    )
    da_hours = x.get(
        "intelligent_tiering_deep_archive_access_restore_hours" + suffix,
        x["intelligent_tiering_deep_archive_access_restore_hours"],
    )
    restore_h = np.array([0.0, 0.0, 0.0, aa_hours, da_hours])
    get_fee = x["intelligent_tiering_get_per_1000"] / 1000
    put_fee = x["intelligent_tiering_put_per_1000"] / 1000
    monitor_fee = x["intelligent_tiering_monitoring_per_1000_objects"] / 1000
    eligible = sizes >= x["intelligent_tiering_min_object_kb"] * BYTES_PER_KB
    size_gb = sizes / BYTES_PER_GB
    d_inf = x["intelligent_tiering_days_to_infrequent"]
    d_ai = x["intelligent_tiering_days_to_archive_instant"]

    ledger = _Ledger(n_days, n, weight)
    waits = WaitStats()
    all_ids = np.arange(n)
    for day in range(n_days):
        idle = day - last - 1
        tier = np.zeros(n, dtype=np.int64)
        tier[idle >= d_inf] = 1
        tier[idle >= d_ai] = 2
        if cfg.archive_access_days is not None:
            tier[idle >= cfg.archive_access_days] = 3
        if cfg.deep_archive_access_days is not None:
            tier[idle >= cfg.deep_archive_access_days] = 4
        tier[~eligible] = 0

        counts = reads_by_day[day]
        ids = np.flatnonzero(counts)
        if len(ids):
            c = counts[ids]
            waits.reads += float((c * weight[ids]).sum())
            ledger.charge("read_requests", day, ids, c * get_fee)
            waits.add(restore_h[tier[ids]], c, weight[ids])  # restores are free (I3)
            last[ids] = day

        new = np.flatnonzero(created == day) if day > 0 else np.zeros(0, dtype=np.int64)
        ledger.charge("write_requests", day, new, np.full(len(new), put_fee))
        ids = all_ids[created <= day]
        tier_now, f = tier[ids], factor[day]
        ledger.charge("storage", day, ids, size_gb[ids] * price[tier_now] * f)
        ledger.charge("overhead_storage", day, ids, overhead_month[tier_now] * f)
        ledger.charge("monitoring", day, ids, np.where(eligible[ids], monitor_fee * f, 0.0))

    return SimResult(
        cloud="aws-intelligent-tiering",
        costs={c: float(v.sum()) for c, v in ledger.daily.items()},
        daily=ledger.daily,
        per_object=ledger.per_object,
        waits=waits,
    )


def simulate_autoclass(
    sheet: PriceSheet,
    inventory: Inventory,
    reads: npt.ArrayLike,
    start: date,
    terminal: str = "nearline",
    initial_idle_days: npt.ArrayLike | int = 0,
) -> SimResult:
    if sheet.cloud != "gcs":
        raise ValueError("Autoclass needs the Google Cloud price sheet")
    if terminal not in {"nearline", "archive"}:
        raise ValueError("terminal must be 'nearline' or 'archive'")
    x = {k: p.value for k, p in sheet.extras.items()}
    prep = _prepare(inventory, reads, initial_idle_days)
    sizes, weight, created, reads_by_day, last = (
        prep.sizes,
        prep.weight,
        prep.created,
        prep.reads_by_day,
        prep.last.copy(),
    )
    n, n_days = len(sizes), reads_by_day.shape[0]
    factor = daily_storage_factor(rules_for(sheet), start, n_days)

    names = ["standard", "nearline", "coldline", "archive"]
    price = np.array([sheet.get(t, "storage_usd_per_gb_month") for t in names])
    read_fee = sheet.get("standard", "class_b_per_1000") / 1000  # I3: Standard rate for all ops
    up_fee = sheet.get("standard", "class_a_per_1000") / 1000
    charged_up = np.array([False, False, True, True])  # from Coldline or Archive (I3)
    fee_per_day = x["autoclass_management_per_1000_objects"] / 1000 / 30  # A8
    eligible = sizes >= x["autoclass_min_object_kb"] * BYTES_PER_KB
    size_gb = sizes / BYTES_PER_GB

    ledger = _Ledger(n_days, n, weight)
    waits = WaitStats()
    all_ids = np.arange(n)
    for day in range(n_days):
        idle = day - last - 1
        tier = np.zeros(n, dtype=np.int64)
        tier[idle >= x["autoclass_days_to_nearline"]] = 1
        if terminal == "archive":
            tier[idle >= x["autoclass_days_to_coldline"]] = 2
            tier[idle >= x["autoclass_days_to_archive"]] = 3
        tier[~eligible] = 0

        counts = reads_by_day[day]
        ids = np.flatnonzero(counts)
        if len(ids):
            c = counts[ids]
            waits.reads += float((c * weight[ids]).sum())
            ledger.charge("read_requests", day, ids, c * read_fee)
            ledger.charge("transition", day, ids, np.where(charged_up[tier[ids]], up_fee, 0.0))
            last[ids] = day

        new = np.flatnonzero(created == day) if day > 0 else np.zeros(0, dtype=np.int64)
        ledger.charge("write_requests", day, new, np.full(len(new), up_fee))  # Class A, Standard
        ids = all_ids[created <= day]
        ledger.charge("storage", day, ids, size_gb[ids] * price[tier[ids]] * factor[day])
        ledger.charge("monitoring", day, ids, np.where(eligible[ids], fee_per_day, 0.0))

    return SimResult(
        cloud="gcs-autoclass",
        costs={c: float(v.sum()) for c, v in ledger.daily.items()},
        daily=ledger.daily,
        per_object=ledger.per_object,
        waits=waits,
    )
