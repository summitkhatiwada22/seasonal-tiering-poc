"""Load and validate cloud price sheets from ``configs/prices/*.yaml``.

Every price the simulator uses comes through this module, so each number carries its provenance:
a value is either ``sourced`` (it appears in a cited official page) or ``unverified`` (not yet
checked; none are left since 2026-10-30, and a test keeps it that way). Malformed sheets fail
loudly instead of silently producing wrong costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ALLOWED_STATUS = frozenset({"sourced", "unverified"})

REQUIRED_TIER_FIELDS = (
    "storage_usd_per_gb_month",
    "retrieval_usd_per_gb",
    "min_storage_days",
    "min_billable_object_kb",
    "per_object_overhead_kb",
    "restore_hours",
)


class PriceSheetError(ValueError):
    """A price sheet is missing something or contains an invalid value."""


@dataclass(frozen=True)
class Priced:
    """One number plus where it came from."""

    value: float
    status: str
    source: str


@dataclass(frozen=True)
class PriceSheet:
    cloud: str
    region: str
    currency: str
    as_of: date
    tier_order: tuple[str, ...]
    tiers: dict[str, dict[str, Priced]]
    extras: dict[str, Priced]

    def get(self, tier: str, field: str) -> float:
        """Value of ``field`` for ``tier`` (raises KeyError if absent)."""
        return self.tiers[tier][field].value

    def unverified(self) -> list[str]:
        """Dotted paths of every value still marked unverified."""
        paths = [
            f"{tier}.{name}"
            for tier, fields in self.tiers.items()
            for name, priced in fields.items()
            if priced.status == "unverified"
        ]
        paths += [f"extras.{name}" for name, p in self.extras.items() if p.status == "unverified"]
        return sorted(paths)


def _priced(where: str, raw: Any) -> Priced:
    if not isinstance(raw, dict):
        raise PriceSheetError(f"{where}: expected a mapping with value, status, source")
    missing = {"value", "status", "source"} - set(raw)
    if missing:
        raise PriceSheetError(f"{where}: missing {sorted(missing)}")
    value, status, source = raw["value"], raw["status"], raw["source"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PriceSheetError(f"{where}: value must be a number, got {value!r}")
    if value < 0:
        raise PriceSheetError(f"{where}: value must not be negative, got {value}")
    if status not in ALLOWED_STATUS:
        raise PriceSheetError(f"{where}: status must be one of {sorted(ALLOWED_STATUS)}")
    if not isinstance(source, str) or not source:
        raise PriceSheetError(f"{where}: source must be a non-empty string")
    if status == "sourced" and not source.startswith("http"):
        raise PriceSheetError(f"{where}: a sourced value needs an http(s) source URL")
    return Priced(value=float(value), status=status, source=source)


def load_price_sheet(path: Path) -> PriceSheet:
    """Read and validate one price sheet."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PriceSheetError(f"{path.name}: top level must be a mapping")
    for key in ("cloud", "region", "currency", "as_of", "tier_order", "tiers"):
        if key not in raw:
            raise PriceSheetError(f"{path.name}: missing '{key}'")
    if not isinstance(raw["as_of"], date):
        raise PriceSheetError(f"{path.name}: as_of must be a date like 2026-10-29")

    tier_order = tuple(raw["tier_order"])
    if set(tier_order) != set(raw["tiers"]):
        raise PriceSheetError(f"{path.name}: tier_order and tiers must list the same tiers")

    tiers: dict[str, dict[str, Priced]] = {}
    for tier, fields in raw["tiers"].items():
        if not isinstance(fields, dict):
            raise PriceSheetError(f"{path.name}: tier '{tier}' must be a mapping")
        for required in REQUIRED_TIER_FIELDS:
            if required not in fields:
                raise PriceSheetError(f"{path.name}: tier '{tier}' is missing '{required}'")
        tiers[tier] = {
            name: _priced(f"{path.name}:{tier}.{name}", item) for name, item in fields.items()
        }

    extras = {
        name: _priced(f"{path.name}:extras.{name}", item)
        for name, item in (raw.get("extras") or {}).items()
    }
    return PriceSheet(
        cloud=str(raw["cloud"]),
        region=str(raw["region"]),
        currency=str(raw["currency"]),
        as_of=raw["as_of"],
        tier_order=tier_order,
        tiers=tiers,
        extras=extras,
    )


def load_all(directory: Path) -> dict[str, PriceSheet]:
    """Load every ``*.yaml`` sheet in ``directory``, keyed by cloud name."""
    sheets = [load_price_sheet(p) for p in sorted(directory.glob("*.yaml"))]
    return {sheet.cloud: sheet for sheet in sheets}
