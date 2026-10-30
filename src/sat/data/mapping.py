"""Turn demand (views, downloads, checkouts) into storage reads (decision D-031).

A page view or a download is a sign of demand, not a read from cold storage: caches, CDNs and
mirrors absorb most of it. We do not know by how much, so demand is scaled down to an archive's
read level and the scale is a stated setting, reported at three values:

    reads[i, d] ~ Poisson(scale_i * demand[i, d])

``scale`` is chosen so that the *median object's* average reads per day over the training years
2016-2022 equals a target: 0.005 (low, about 2 reads a year), 0.05 (central, about 18 a year; the
same median rate the synthetic dataset D7 uses) or 0.5 (high, about 180 a year). Only training
years enter the calibration. The shape of each object's demand over the year, and the spread of
popularity between objects, are kept exactly in expectation.

D1 has two cohorts drawn by different rules (most-viewed and random, D-019); they differ by about
3,000x in median views, a sampling artefact rather than a property of an archive, so each cohort is
calibrated to the target on its own.

Reads are drawn one calendar year at a time from a random stream fixed by (seed, dataset, year,
setting), so a year's reads are identical whether the table is loaded up to 2022 (tuning) or up to
2023 (validation).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import numpy.typing as npt

from sat.data.demand import Demand
from sat.data.sealed import TUNING_YEAR

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

READ_TARGETS: dict[str, float] = {"low": 0.005, "central": 0.05, "high": 0.5}
SETTING_CODE = {"low": 1, "central": 2, "high": 3}
DATASET_CODE = {"D1": 1, "D3": 3, "D4": 4}
READ_SEED = 20261030


def calibration_rates(demand: Demand) -> FloatArray:
    """Each object's mean demand per day from its first demand day to the end of 2022.

    NaN for objects with no demand in 2016-2022 (they are left out of the median)."""
    end = min(demand.day_index(date(TUNING_YEAR, 12, 31)) + 1, demand.n_days)
    first = demand.first_demand_day()
    total = demand.counts[:, :end].sum(axis=1)
    span = (end - first).astype(np.float64)
    rates = np.full(len(demand.names), np.nan)
    ok = (first < end) & (span > 0)
    rates[ok] = total[ok] / span[ok]
    return rates


def scales(demand: Demand, target: float, by_group: tuple[str, ...] = ()) -> FloatArray:
    """Per-object scale so the median calibration rate (per group, if given) equals ``target``."""
    rates = calibration_rates(demand)
    out = np.full(len(demand.names), np.nan)
    masks = [demand.groups[g] for g in by_group] or [np.ones(len(demand.names), dtype=bool)]
    covered = np.zeros(len(demand.names), dtype=bool)
    for mask in masks:
        if (covered & mask).any():
            raise ValueError("calibration groups must not overlap")
        covered |= mask
        median = float(np.nanmedian(rates[mask]))
        if not median > 0:
            raise ValueError("median training demand is zero; cannot calibrate")
        out[mask] = target / median
    if not covered.all():
        raise ValueError("calibration groups must cover every object")
    return out


def default_scales(demand: Demand, setting: str) -> FloatArray:
    by_group = ("cohort_A", "cohort_B") if demand.dataset == "D1" else ()
    return scales(demand, READ_TARGETS[setting], by_group)


def to_reads(demand: Demand, scale: FloatArray, setting: str, seed: int = READ_SEED) -> IntArray:
    """Integer reads per object and day, drawn year by year (see module docstring)."""
    if scale.shape != (len(demand.names),) or not np.isfinite(scale).all() or (scale < 0).any():
        raise ValueError("scale must be finite, non-negative, one per object")
    reads = np.zeros(demand.counts.shape, dtype=np.int64)
    year = demand.start.year
    while True:
        c0 = demand.day_index(date(year, 1, 1))
        if c0 >= demand.n_days:
            break
        c1 = min(demand.day_index(date(year + 1, 1, 1)), demand.n_days)
        rng = np.random.default_rng(
            [seed, DATASET_CODE.get(demand.dataset, 0), year, SETTING_CODE[setting]]
        )
        reads[:, c0:c1] = rng.poisson(scale[:, None] * demand.counts[:, c0:c1])
        year += 1
    return reads
