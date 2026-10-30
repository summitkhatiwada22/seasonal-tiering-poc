"""How each cloud turns prices into a bill. Every rule is cited in docs/SIM_RULES.md.

Numbers live in the price sheets; this module only holds the *semantics* (which price applies when).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from sat.prices import PriceSheet

BYTES_PER_GB = 2**30  # U1: all three clouds bill binary GB
BYTES_PER_KB = 1024  # U2


@dataclass(frozen=True)
class CloudRules:
    cloud: str
    storage_proration: str  # S1: "calendar_month" (monthly / days in month) or "hours_730"
    early_delete_basis: str  # E3: "calendar_month", "days_30" or "hours_730"
    lifecycle_keeps_clock: bool  # E4: Google lifecycle moves keep the creation clock
    down_fee_field: str  # M1: per-1,000 field of the destination class
    up_fee_field: str  # M2: per-1,000 field; "dest" or "source" given by up_fee_on
    up_fee_on: str
    read_field: str  # R1: per-1,000 read request field
    write_field: str  # per-1,000 write request field
    overhead_other_kb: float  # S3: part of the per-object overhead billed at another class's rate
    overhead_other_tier: str | None
    copy_tier: str | None  # T2: class whose storage rate a temporary copy pays
    copy_write_field: str | None  # T2: Azure pays a write on the destination blob
    copy_read_on_archive: bool  # T6: AWS reads the copy at the archive class's GET price
    restore_fee_by_speed: dict[str, str]  # speed -> per-1,000 request field on the archive class
    retrieval_by_speed: dict[str, str]  # speed -> per-GB retrieval field on the archive class
    hours_by_speed: dict[str, str]  # speed -> restore-hours field on the archive class
    reissue_costs_a_read: bool  # T4: AWS bills a repeated restore as a GET


AWS_RULES = CloudRules(
    cloud="aws",
    storage_proration="calendar_month",
    early_delete_basis="calendar_month",
    lifecycle_keeps_clock=False,
    down_fee_field="transition_in_per_1000",
    up_fee_field="put_per_1000",
    up_fee_on="dest",
    read_field="get_per_1000",
    write_field="put_per_1000",
    overhead_other_kb=8.0,
    overhead_other_tier="standard",
    copy_tier="standard",
    copy_write_field=None,
    copy_read_on_archive=True,
    restore_fee_by_speed={
        "standard": "restore_request_per_1000",
        "bulk": "restore_request_bulk_per_1000",
        "expedited": "restore_request_expedited_per_1000",
    },
    retrieval_by_speed={
        "standard": "retrieval_usd_per_gb",
        "bulk": "retrieval_bulk_usd_per_gb",
        "expedited": "retrieval_expedited_usd_per_gb",
    },
    hours_by_speed={
        "standard": "restore_hours",
        "bulk": "bulk_restore_hours",
        "expedited": "expedited_restore_hours",
    },
    reissue_costs_a_read=True,
)

GCS_RULES = CloudRules(
    cloud="gcs",
    storage_proration="hours_730",
    early_delete_basis="hours_730",
    lifecycle_keeps_clock=True,
    down_fee_field="class_a_per_1000",
    up_fee_field="class_a_per_1000",
    up_fee_on="dest",
    read_field="class_b_per_1000",
    write_field="class_a_per_1000",
    overhead_other_kb=0.0,
    overhead_other_tier=None,
    copy_tier=None,
    copy_write_field=None,
    copy_read_on_archive=False,
    restore_fee_by_speed={},
    retrieval_by_speed={},
    hours_by_speed={},
    reissue_costs_a_read=False,
)

AZURE_RULES = CloudRules(
    cloud="azure",
    storage_proration="calendar_month",
    early_delete_basis="days_30",
    lifecycle_keeps_clock=False,
    down_fee_field="put_per_1000",
    up_fee_field="get_per_1000",
    up_fee_on="source",
    read_field="get_per_1000",
    write_field="put_per_1000",
    overhead_other_kb=8.0,  # A6: all 8 KB of archive metadata at the cool rate
    overhead_other_tier="cool",
    copy_tier="hot",
    copy_write_field="put_per_1000",
    copy_read_on_archive=False,
    restore_fee_by_speed={"standard": "get_per_1000", "high": "get_priority_per_1000"},
    retrieval_by_speed={
        "standard": "retrieval_usd_per_gb",
        "high": "retrieval_priority_usd_per_gb",
    },
    hours_by_speed={"standard": "restore_hours", "high": "priority_restore_hours"},
    reissue_costs_a_read=False,
)

RULES = {r.cloud: r for r in (AWS_RULES, GCS_RULES, AZURE_RULES)}


def rules_for(sheet: PriceSheet) -> CloudRules:
    try:
        return RULES[sheet.cloud]
    except KeyError as exc:
        raise ValueError(f"no billing rules for cloud {sheet.cloud!r}") from exc


def day_dates(start: date, n_days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n_days)]


def days_in_month(day: date) -> int:
    nxt = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return (nxt - date(day.year, day.month, 1)).days


def daily_storage_factor(rules: CloudRules, start: date, n_days: int) -> npt.NDArray[np.float64]:
    """Multiply a monthly price by this to get one day's charge (S1)."""
    if rules.storage_proration == "hours_730":
        return np.full(n_days, 24 / 730)
    return np.array([1 / days_in_month(d) for d in day_dates(start, n_days)])


def early_delete_factor(rules: CloudRules, leave_day: date) -> float:
    """Monthly price x this x remaining days = early deletion charge (E3)."""
    if rules.early_delete_basis == "hours_730":
        return 24 / 730
    if rules.early_delete_basis == "days_30":
        return 1 / 30
    return 1 / days_in_month(leave_day)


def tier_field(sheet: PriceSheet, tier: str, name: str, default: float = 0.0) -> float:
    fields = sheet.tiers[tier]
    return fields[name].value if name in fields else default


def is_archive(sheet: PriceSheet, tier: str) -> bool:
    """Archive (offline) classes need a restore before a read (restore_hours > 0)."""
    return tier_field(sheet, tier, "restore_hours") > 0


def restore_hours(sheet: PriceSheet, rules: CloudRules, tier: str, speed: str, end: str) -> float:
    if speed not in rules.hours_by_speed:
        raise ValueError(f"{rules.cloud}: unknown restore speed {speed!r}")
    field = rules.hours_by_speed[speed]
    if field not in sheet.tiers[tier]:
        raise ValueError(f"{rules.cloud}: {tier} has no {speed} restore")
    high = tier_field(sheet, tier, field)
    if end == "low":
        return tier_field(sheet, tier, field + "_low", high)  # T5: low = high where none stated
    return high
