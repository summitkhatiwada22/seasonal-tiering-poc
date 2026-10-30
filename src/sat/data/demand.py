"""Daily demand tables for the policy experiments, read behind the sealed-year lock.

A ``Demand`` holds one row per object and one column per day from 2016-01-01: page views (D1),
package downloads (D3) or library checkouts (D4, monthly totals spread evenly over the days of the
month). Demand is not yet a storage read; ``sat.data.mapping`` turns it into reads.

Every loader takes ``max_year``: it opens only the ``year=YYYY`` partitions up to that year and
refuses any sealed year (``sat.data.sealed``).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from sat.data.sealed import FIRST_YEAR, check_year, year_partitions

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.int64]

START = date(FIRST_YEAR, 1, 1)
RECORDS = Path(__file__).resolve().parents[3] / "data_records"


@dataclass(frozen=True)
class Demand:
    dataset: str
    names: tuple[str, ...]
    start: date
    counts: FloatArray  # (objects, days), expected demand per day
    resolution: str = "daily"  # "daily" or "monthly" (D4: within-month timing unknown)
    groups: dict[str, BoolArray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.counts.ndim != 2 or self.counts.shape[0] != len(self.names):
            raise ValueError("counts must have one row per object")
        if (self.counts < 0).any() or not np.isfinite(self.counts).all():
            raise ValueError("demand must be finite and non-negative")
        for name, mask in self.groups.items():
            if mask.shape != (len(self.names),):
                raise ValueError(f"group {name!r} must have one flag per object")

    @property
    def n_days(self) -> int:
        return int(self.counts.shape[1])

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.n_days - 1)

    def day_index(self, day: date) -> int:
        return (day - self.start).days

    def first_demand_day(self) -> IntArray:
        """Index of each object's first day with demand (``n_days`` if it never has any).

        Used as the object's creation day: an object with no demand yet is treated as not stored
        yet (D-031)."""
        has = self.counts > 0
        first = has.argmax(axis=1).astype(np.int64)
        first[~has.any(axis=1)] = self.n_days
        return first


def _days(max_year: int) -> int:
    return (date(max_year, 12, 31) - START).days + 1


def _dense(
    frames: list[pl.DataFrame], key: str, names: list[str], max_year: int, value: str = "views"
) -> FloatArray:
    """Pivot long (key, date, value) rows into an objects x days matrix in ``names`` order."""
    index = {n: i for i, n in enumerate(names)}
    out = np.zeros((len(names), _days(max_year)))
    for frame in frames:
        rows = frame.select(
            pl.col(key).replace_strict(index, default=-1, return_dtype=pl.Int64).alias("row"),
            ((pl.col("date") - pl.lit(START)).dt.total_days()).alias("col"),
            pl.col(value).cast(pl.Float64).alias("v"),
        )
        unknown = rows.filter(pl.col("row") < 0).height
        if unknown:
            raise ValueError(f"{unknown} rows for objects not in the saved list")
        r, c, v = (rows[x].to_numpy() for x in ("row", "col", "v"))
        np.add.at(out, (r, c), v)
    return out


def _flags(path: Path, names: list[str]) -> BoolArray:
    with path.open(newline="", encoding="utf-8") as fh:
        flagged = {row["article"] for row in csv.DictReader(fh) if row["flags"].strip()}
    return np.array([n in flagged for n in names])


def load_d1(root: Path, max_year: int, records: Path = RECORDS) -> Demand:
    """Wikipedia daily user page views for the saved 10,000-article list (D-014, D-019)."""
    with (records / "D1" / "articles.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    names = [r["article"] for r in rows]
    cohort = np.array([r["cohort"] for r in rows])
    parts = year_partitions(root / "D1", range(FIRST_YEAR, max_year + 1), max_year)
    frames = [pl.read_parquet(p / "views.parquet") for p in parts]
    counts = _dense(frames, "article", names, max_year)
    groups = {
        "cohort_A": cohort == "A",
        "cohort_B": cohort == "B",
        "flagged": _flags(records / "D1" / "flags.csv", names),
    }
    return Demand("D1", tuple(names), START, counts, "daily", groups)


def load_d3(root: Path, max_year: int, records: Path = RECORDS) -> Demand:
    """npm daily downloads for the saved 300-package list (D-024)."""
    with (records / "D3" / "packages.csv").open(newline="", encoding="utf-8") as fh:
        names = [r["package"] for r in csv.DictReader(fh)]
    parts = year_partitions(root / "D3", range(FIRST_YEAR, max_year + 1), max_year)
    frames = [pl.read_parquet(p / "views.parquet") for p in parts]
    counts = _dense(frames, "package", names, max_year)
    groups = {"flagged": _flags(records / "D3" / "flags.csv", names)}
    return Demand("D3", tuple(names), START, counts, "daily", groups)


def split_d4_sample(sample_dir: Path, out_dir: Path) -> None:
    """Write the D4 sample's monthly rows as ``year=YYYY`` partitions so the lock can apply."""
    monthly = pl.read_parquet(sample_dir / "d4_sample_monthly.parquet")
    for (year,), part in monthly.group_by("year"):
        check_year(int(year), max_year=int(year))  # never writes a sealed partition
        folder = out_dir / f"year={int(year)}"
        folder.mkdir(parents=True, exist_ok=True)
        part.sort("key_id", "month").write_parquet(folder / "monthly.parquet")
    keys = pl.read_parquet(sample_dir / "d4_sample_keys.parquet")
    keys.write_parquet(out_dir / "keys.parquet")


def load_d4(sample_root: Path, max_year: int) -> Demand:
    """Seattle library checkouts of the 10,000-title sample (D-030), monthly spread evenly."""
    keys = pl.read_parquet(sample_root / "keys.parquet").sort("key_id")
    n = keys.height
    if keys["key_id"].to_list() != list(range(n)):
        raise ValueError("D4 sample keys must be numbered 0..n-1")
    parts = year_partitions(sample_root, range(FIRST_YEAR, max_year + 1), max_year)
    counts = np.zeros((n, _days(max_year)))
    for part in parts:
        frame = pl.read_parquet(part / "monthly.parquet")
        for (year, month), rows in frame.group_by("year", "month"):
            first = date(int(year), int(month), 1)
            nxt = date(int(year) + (int(month) == 12), int(month) % 12 + 1, 1)
            c0, c1 = (first - START).days, (nxt - START).days
            ids = rows["key_id"].to_numpy()
            per_day = rows["checkouts"].to_numpy().astype(np.float64) / (c1 - c0)
            counts[ids, c0:c1] += per_day[:, None]
    names = [
        f"{u}|{m}|{t}|{c}"
        for u, m, t, c in keys.select("usageclass", "materialtype", "title", "creator").iter_rows()
    ]
    usage = keys["usageclass"].to_numpy()
    groups = {"physical": usage == "Physical", "digital": usage == "Digital"}
    return Demand("D4", tuple(names), START, counts, "monthly", groups)
