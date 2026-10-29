"""Synthetic access-log generator (dataset D7).

Plants *known* access patterns so later phases can check that the pipeline finds what we put in
and finds nothing when nothing was planted. Five kinds of object:

* ``evergreen``       constant daily read rate
* ``annual_seasonal`` low baseline plus one yearly peak (the pattern the product is built for)
* ``weekly``          busy on weekdays, quiet at weekends
* ``decaying``        created on some day, then read less and less (news-style content)
* ``sporadic``        almost never read, with rare one-off bursts

Output is two tables:

* ``objects``  one row per object, including the ground-truth parameters (``peak_doy`` etc.)
* ``reads``    sparse daily counts: only (object, day) pairs with at least one read

Determinism: output depends only on the config. Object parameters come from one random stream and
each block of ``CHUNK_OBJECTS`` objects gets its own stream, so results are reproducible and a block
can be regenerated alone. Day-of-year uses the real calendar, leap years included.

``seasonality=False`` builds the *control*: the same objects and the same expected read volume,
but each seasonal object's yearly peak is flattened into a constant rate. Any "seasonal gain"
measured on the control is a false win.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import numpy.typing as npt
import polars as pl

CATEGORIES: tuple[str, ...] = ("evergreen", "annual_seasonal", "weekly", "decaying", "sporadic")

DEFAULT_MIX: dict[str, float] = {
    "evergreen": 0.40,
    "annual_seasonal": 0.15,
    "weekly": 0.15,
    "decaying": 0.15,
    "sporadic": 0.15,
}

CHUNK_OBJECTS = 5_000
_CYCLE = 365  # days in the seasonal cycle

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class SynthConfig:
    n_objects: int = 10_000
    start: date = date(2021, 1, 1)
    n_days: int = 3 * 365
    seed: int = 42
    seasonality: bool = True
    mix: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_MIX))

    def __post_init__(self) -> None:
        if self.n_objects <= 0:
            raise ValueError("n_objects must be positive")
        if self.n_days <= 0:
            raise ValueError("n_days must be positive")
        unknown = set(self.mix) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"unknown categories in mix: {sorted(unknown)}")
        if any(share < 0 for share in self.mix.values()):
            raise ValueError("mix shares must not be negative")
        if not math.isclose(sum(self.mix.values()), 1.0, abs_tol=1e-9):
            raise ValueError("mix shares must sum to 1")


@dataclass(frozen=True)
class SynthData:
    objects: pl.DataFrame
    reads: pl.DataFrame


def _n_chunks(cfg: SynthConfig) -> int:
    return -(-cfg.n_objects // CHUNK_OBJECTS)


def make_objects(cfg: SynthConfig) -> pl.DataFrame:
    """One row per object, with ground-truth pattern parameters (null where not applicable)."""
    rng = np.random.default_rng(np.random.SeedSequence(cfg.seed).spawn(1)[0])
    n = cfg.n_objects

    names = [c for c in CATEGORIES if c in cfg.mix]
    probs = np.array([cfg.mix[c] for c in names])
    category = [names[i] for i in rng.choice(len(names), size=n, p=probs)]

    # Every parameter is drawn for every object so the random stream never depends on category.
    size_bytes = np.clip(np.exp(rng.normal(math.log(2e5), 2.0, n)), 1e3, 5e9).astype(np.uint64)
    base_rate = np.exp(rng.normal(math.log(0.05), 1.5, n))  # reads per day; most objects are cold
    peak_doy = rng.integers(0, _CYCLE, n)
    peak_width = rng.uniform(8.0, 25.0, n)
    peak_mult = rng.uniform(20.0, 100.0, n)
    half_life = rng.uniform(7.0, 60.0, n)
    created_day = rng.integers(0, cfg.n_days, n)

    is_seasonal = pl.col("category") == "annual_seasonal"
    is_decaying = pl.col("category") == "decaying"
    return (
        pl.DataFrame(
            {
                "object_id": np.arange(n, dtype=np.uint32),
                "category": category,
                "size_bytes": size_bytes,
                "base_rate": base_rate,
                "peak_doy": peak_doy.astype(np.int16),
                "peak_width_days": peak_width,
                "peak_multiplier": peak_mult,
                "half_life_days": half_life,
                "created_day": created_day.astype(np.int32),
            }
        )
        .with_columns(
            pl.when(is_seasonal).then(pl.col("peak_doy")).otherwise(None).alias("peak_doy"),
            pl.when(is_seasonal)
            .then(pl.col("peak_width_days"))
            .otherwise(None)
            .alias("peak_width_days"),
            pl.when(is_seasonal)
            .then(pl.col("peak_multiplier"))
            .otherwise(None)
            .alias("peak_multiplier"),
            pl.when(is_decaying)
            .then(pl.col("half_life_days"))
            .otherwise(None)
            .alias("half_life_days"),
            pl.when(is_decaying).then(pl.col("created_day")).otherwise(0).alias("created_day"),
        )
        .with_columns(
            (pl.lit(cfg.start, dtype=pl.Date) + pl.duration(days=pl.col("created_day"))).alias(
                "created_date"
            )
        )
    )


def _circular_distance(a: FloatArray, b: FloatArray) -> FloatArray:
    diff: FloatArray = np.abs(a - b)
    wrapped: FloatArray = np.minimum(diff, _CYCLE - diff)
    return wrapped


def _simulate_chunk(cfg: SynthConfig, chunk: pl.DataFrame, rng: np.random.Generator) -> IntArray:
    """Daily read counts for one block of objects: shape (objects, days)."""
    t = np.arange(cfg.n_days)
    days = np.datetime64(cfg.start, "D") + t
    doy = (days - days.astype("datetime64[Y]").astype("datetime64[D]")).astype(np.int64)
    weekday = (days.astype(np.int64) + 3) % 7  # Monday = 0; 1970-01-01 was a Thursday

    cat = chunk["category"].to_numpy()
    base = chunk["base_rate"].to_numpy()
    rate = np.repeat(base[:, None], cfg.n_days, axis=1)  # evergreen is just the base rate

    seasonal = cat == "annual_seasonal"
    if seasonal.any():
        peak = chunk["peak_doy"].fill_null(0).to_numpy()[seasonal].astype(np.float64)
        width = chunk["peak_width_days"].fill_null(1.0).to_numpy()[seasonal]
        mult = chunk["peak_multiplier"].fill_null(0.0).to_numpy()[seasonal]
        if cfg.seasonality:
            dist = _circular_distance(doy[None, :].astype(np.float64), peak[:, None])
            curve = np.exp(-0.5 * (dist / width[:, None]) ** 2)
        else:
            # Control: same expected volume, peak flattened to its yearly average.
            grid = np.arange(_CYCLE, dtype=np.float64)
            dist = _circular_distance(grid[None, :], peak[:, None])
            curve = np.exp(-0.5 * (dist / width[:, None]) ** 2).mean(axis=1, keepdims=True)
        rate[seasonal] = base[seasonal][:, None] * (1.0 + mult[:, None] * curve)

    weekly = cat == "weekly"
    rate[weekly] = base[weekly][:, None] * np.where(weekday >= 5, 0.2, 1.6)[None, :]

    decaying = cat == "decaying"
    if decaying.any():
        created = chunk["created_day"].to_numpy()[decaying].astype(np.float64)
        half_life = chunk["half_life_days"].fill_null(30.0).to_numpy()[decaying]
        age = t[None, :] - created[:, None]
        fade = np.exp(-math.log(2.0) * np.maximum(age, 0.0) / half_life[:, None])
        rate[decaying] = np.where(age >= 0, base[decaying][:, None] * 10.0 * fade, 0.0)

    sporadic = cat == "sporadic"
    rate[sporadic] = base[sporadic][:, None] * 0.1

    counts: IntArray = rng.poisson(rate).astype(np.int64)
    bursts = rng.binomial(1, 0.002, size=counts.shape) * rng.poisson(15.0, size=counts.shape)
    counts += np.where(sporadic[:, None], bursts, 0)
    return counts


def generate_chunks(cfg: SynthConfig) -> Iterator[tuple[pl.DataFrame, pl.DataFrame]]:
    """Yield ``(objects, reads)`` one block of objects at a time (memory stays bounded)."""
    objects = make_objects(cfg)
    n_chunks = _n_chunks(cfg)
    streams = np.random.SeedSequence(cfg.seed).spawn(1 + n_chunks)  # stream 0 made the objects
    start = np.datetime64(cfg.start, "D")

    for k in range(n_chunks):
        lo = k * CHUNK_OBJECTS
        hi = min(lo + CHUNK_OBJECTS, cfg.n_objects)
        chunk = objects.slice(lo, hi - lo)
        counts = _simulate_chunk(cfg, chunk, np.random.default_rng(streams[1 + k]))
        obj_idx, day_idx = np.nonzero(counts)
        dates = (start + day_idx).astype("datetime64[ms]")
        reads = pl.DataFrame(
            {
                "object_id": (obj_idx + lo).astype(np.uint32),
                "date": pl.Series("date", dates).cast(pl.Date),
                "reads": counts[obj_idx, day_idx].astype(np.uint32),
            }
        )
        yield chunk, reads


def generate(cfg: SynthConfig) -> SynthData:
    """Generate everything in memory. Fine for scales S and M; see ``generate_chunks`` for L."""
    parts = list(generate_chunks(cfg))
    return SynthData(
        objects=pl.concat([objects for objects, _ in parts]),
        reads=pl.concat([reads for _, reads in parts]),
    )
