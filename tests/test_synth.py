from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from sat.synth import CHUNK_OBJECTS, SynthConfig, generate

THREE_YEARS = 3 * 365


def _cfg(**overrides: object) -> SynthConfig:
    params: dict[str, object] = {"n_objects": 2_000, "n_days": THREE_YEARS, "seed": 7}
    params.update(overrides)
    return SynthConfig(**params)  # type: ignore[arg-type]


def _seasonal_share_near_peak(data_objects: pl.DataFrame, reads: pl.DataFrame) -> float:
    """Share of seasonal objects' reads that fall within 20 days of their planted peak."""
    seasonal = data_objects.filter(pl.col("category") == "annual_seasonal").select(
        "object_id", "peak_doy"
    )
    joined = reads.join(seasonal, on="object_id").with_columns(
        (pl.col("date").dt.ordinal_day() - 1).alias("doy")
    )
    diff = (pl.col("doy") - pl.col("peak_doy")).abs()
    near = pl.min_horizontal(diff, 365 - diff) <= 20
    total = joined["reads"].sum()
    return float(joined.filter(near)["reads"].sum()) / float(total)


def test_same_seed_gives_identical_data() -> None:
    a, b = generate(_cfg()), generate(_cfg())
    assert a.objects.equals(b.objects)
    assert a.reads.equals(b.reads)


def test_different_seed_gives_different_data() -> None:
    assert not generate(_cfg(seed=1)).reads.equals(generate(_cfg(seed=2)).reads)


def test_schema_and_ranges() -> None:
    cfg = _cfg()
    data = generate(cfg)
    assert data.objects.height == cfg.n_objects
    assert data.objects["object_id"].to_list() == list(range(cfg.n_objects))
    assert data.objects["size_bytes"].min() >= 1_000  # type: ignore[operator]
    assert data.reads.schema["date"] == pl.Date
    assert data.reads["reads"].min() >= 1  # type: ignore[operator]
    last_day = cfg.start + timedelta(days=cfg.n_days - 1)
    assert data.reads["date"].min() >= cfg.start  # type: ignore[operator]
    assert data.reads["date"].max() <= last_day  # type: ignore[operator]
    assert data.reads["object_id"].max() < cfg.n_objects  # type: ignore[operator]


def test_category_mix_matches_config() -> None:
    cfg = _cfg(n_objects=4_000)
    counts = generate(cfg).objects["category"].value_counts()
    shares = {row[0]: row[1] / cfg.n_objects for row in counts.iter_rows()}
    for category, wanted in cfg.mix.items():
        assert shares[category] == pytest.approx(wanted, abs=0.04)


def test_planted_peaks_are_visible_in_the_data() -> None:
    data = generate(_cfg())
    # A flat pattern would put 41/365 = 11% of reads inside a +-20 day window.
    assert _seasonal_share_near_peak(data.objects, data.reads) > 0.40


def test_control_has_no_peaks_but_the_same_volume() -> None:
    seasonal = generate(_cfg(seasonality=True))
    control = generate(_cfg(seasonality=False))

    assert seasonal.objects.equals(control.objects)  # same objects, same planted truth
    share = _seasonal_share_near_peak(control.objects, control.reads)
    assert 0.05 < share < 0.20  # close to the flat 11%

    def volume(d: pl.DataFrame, reads: pl.DataFrame) -> int:
        ids = d.filter(pl.col("category") == "annual_seasonal")["object_id"]
        return int(reads.filter(pl.col("object_id").is_in(ids.implode()))["reads"].sum())

    ratio = volume(control.objects, control.reads) / volume(seasonal.objects, seasonal.reads)
    assert ratio == pytest.approx(1.0, abs=0.15)


def test_decaying_objects_have_no_reads_before_they_exist() -> None:
    data = generate(_cfg())
    decaying = data.objects.filter(pl.col("category") == "decaying").select(
        "object_id", "created_date"
    )
    early = data.reads.join(decaying, on="object_id").filter(
        pl.col("date") < pl.col("created_date")
    )
    assert early.height == 0
    assert decaying.height > 0


def test_weekly_objects_are_busier_on_weekdays() -> None:
    cfg = _cfg()
    data = generate(cfg)
    weekly_ids = data.objects.filter(pl.col("category") == "weekly")["object_id"]
    reads = data.reads.filter(pl.col("object_id").is_in(weekly_ids.implode())).with_columns(
        (pl.col("date").dt.weekday() >= 6).alias("weekend")
    )
    all_days = [cfg.start + timedelta(days=i) for i in range(cfg.n_days)]
    weekend_days = sum(1 for d in all_days if d.weekday() >= 5)
    weekday_days = len(all_days) - weekend_days
    totals = {
        row[0]: row[1] for row in reads.group_by("weekend").agg(pl.col("reads").sum()).iter_rows()
    }
    per_weekday = totals[False] / weekday_days
    per_weekend = totals[True] / weekend_days
    assert per_weekday / per_weekend > 4  # planted ratio is 8


def test_more_than_one_chunk_still_gives_contiguous_ids() -> None:
    n = CHUNK_OBJECTS + 123
    data = generate(SynthConfig(n_objects=n, n_days=30, seed=3, start=date(2024, 2, 1)))
    assert data.objects["object_id"].to_list() == list(range(n))
    assert data.reads["object_id"].max() < n  # type: ignore[operator]


def test_leap_year_dates_are_real_calendar_dates() -> None:
    data = generate(SynthConfig(n_objects=500, n_days=366, seed=5, start=date(2024, 1, 1)))
    assert date(2024, 2, 29) in set(data.reads["date"].unique().to_list())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"n_objects": 0}, "n_objects"),
        ({"n_days": 0}, "n_days"),
        ({"mix": {"evergreen": 0.5}}, "sum to 1"),
        ({"mix": {"unicorn": 1.0}}, "unknown"),
        ({"mix": {"evergreen": 1.5, "weekly": -0.5}}, "negative"),
    ],
)
def test_bad_config_is_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SynthConfig(**kwargs)  # type: ignore[arg-type]
