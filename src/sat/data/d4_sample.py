"""D4 (Seattle library checkouts): reduce the yearly files to a fixed random sample of titles.

The yearly files are 0.85 GB for 2016-2023, too large to move from the owner's computer at the
measured upload speed, so this runs where the data is and writes two small files:

    python -m sat.data.d4_sample --root <processed/D4> --out <folder> --step population
    python -m sat.data.d4_sample --root <processed/D4> --out <folder> --step extract

Rules (decision D-030):

* **Object key:** ``usageclass, checkouttype, materialtype, title, creator`` exactly as published
  (whitespace stripped, missing creator = empty). Rows with an empty title are dropped. Rows that
  share a key and a month are summed (they differ only in ISBN or publication year). Different
  formats of one book are different objects, as different files would be.
* **Population:** keys with at least one checkout in 2016-2022. Only training years are read to
  build it (``max_year=2022``), so the 2023 validation year cannot influence the sample.
* **Sample:** 10,000 keys drawn uniformly without replacement with ``numpy.random.default_rng(
  20261030)`` from the population sorted by key (a stable order that does not depend on file
  order).
* **Output:** monthly checkouts of the sampled keys for 2016-01 to 2023-12.

Only this module and ``sat.data.sealed`` are needed (with polars and numpy), so the two files can be
copied byte for byte to the computer that holds the data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from sat.data.sealed import FIRST_YEAR, TUNING_YEAR, VALIDATION_YEAR, year_partitions

KEY = ["usageclass", "checkouttype", "materialtype", "title", "creator"]
SAMPLE_SIZE = 10_000
SEED = 20261030


def _keyed(path: Path) -> pl.LazyFrame:
    return (
        pl.scan_parquet(path / "checkouts.parquet")
        .select(
            *[pl.col(c).cast(pl.String).fill_null("").str.strip_chars().alias(c) for c in KEY],
            pl.col("checkoutyear").alias("year"),
            pl.col("checkoutmonth").alias("month"),
            pl.col("checkouts"),
        )
        .filter(pl.col("title") != "")
    )


def population(root: Path) -> pl.DataFrame:
    """Every key with at least one checkout in the training years, sorted by key."""
    parts = year_partitions(root, range(FIRST_YEAR, TUNING_YEAR + 1), max_year=TUNING_YEAR)
    frames = [
        _keyed(p).filter(pl.col("checkouts") > 0).select(KEY).unique().collect() for p in parts
    ]
    return pl.concat(frames).unique().sort(KEY)


def draw(pop: pl.DataFrame, size: int = SAMPLE_SIZE, seed: int = SEED) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    picked = np.sort(rng.choice(pop.height, size=min(size, pop.height), replace=False))
    return pop[picked].with_row_index("key_id")


def extract(root: Path, sample: pl.DataFrame) -> pl.DataFrame:
    """Monthly checkouts of the sampled keys, 2016-01 to 2023-12 (key-months with none omitted)."""
    parts = year_partitions(root, range(FIRST_YEAR, VALIDATION_YEAR + 1), max_year=VALIDATION_YEAR)
    keys = sample.lazy()
    frames = [
        _keyed(p)
        .join(keys, on=KEY, how="inner")
        .group_by("key_id", "year", "month")
        .agg(pl.col("checkouts").sum())
        .collect()
        for p in parts
    ]
    return pl.concat(frames).sort("key_id", "year", "month")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sat.data.d4_sample")
    parser.add_argument("--root", type=Path, required=True, help="processed/D4 folder")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--step", choices=["population", "extract"], required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    pop_file = args.out / "d4_population.parquet"
    if args.step == "population":
        pop = population(args.root)
        pop.write_parquet(pop_file)
        print(f"population: {pop.height:,} keys")
        return 0
    pop = pl.read_parquet(pop_file)
    sample = draw(pop)
    monthly = extract(args.root, sample)
    sample.write_parquet(args.out / "d4_sample_keys.parquet")
    monthly.write_parquet(args.out / "d4_sample_monthly.parquet")
    summary = {
        "rule": "D-030",
        "population_keys_2016_2022": pop.height,
        "sample_size": sample.height,
        "seed": SEED,
        "key": KEY,
        "sample_by_usageclass": dict(sample.group_by("usageclass").len().iter_rows()),
        "population_by_usageclass": dict(pop.group_by("usageclass").len().iter_rows()),
        "sample_by_materialtype_top10": dict(
            sample.group_by("materialtype").len().sort("len", descending=True).head(10).iter_rows()
        ),
        "sample_checkouts_by_year": dict(
            monthly.group_by("year").agg(pl.col("checkouts").sum()).sort("year").iter_rows()
        ),
        "rows": monthly.height,
    }
    (args.out / "d4_sample_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
