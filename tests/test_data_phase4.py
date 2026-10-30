"""Phase 4 data layer: the sealed-year lock, loaders, demand-to-read mapping and sizes."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from sat.data import d4_sample
from sat.data.demand import Demand, load_d1, load_d4, split_d4_sample
from sat.data.mapping import READ_TARGETS, calibration_rates, default_scales, scales, to_reads
from sat.data.sealed import SealedYearError, check_year, year_partitions
from sat.data.sizes import draw_u, size_settings, sizes_for
from sat.data.trace_sizes import object_sizes, summarise

RECORDS = Path(__file__).resolve().parents[1] / "data_records"

# ------------------------------------------------------------------ the lock


def test_sealed_years_are_refused() -> None:
    for year in (2024, 2025, 2026):
        with pytest.raises(SealedYearError):
            check_year(year, max_year=2023)
    with pytest.raises(SealedYearError):
        check_year(2020, max_year=2024)
    with pytest.raises(SealedYearError):
        check_year(2023, max_year=2022)  # the validation year is locked while tuning
    check_year(2023, max_year=2023)
    with pytest.raises(SealedYearError):
        check_year(2024, max_year=2024)  # even when asked for explicitly


def test_partitions_never_open_a_sealed_folder(tmp_path: Path) -> None:
    for year in (2022, 2023, 2024):
        (tmp_path / f"year={year}").mkdir()
    # a sealed folder with unreadable content: listing must not touch it
    (tmp_path / "year=2024" / "views.parquet").write_bytes(b"not parquet")
    (tmp_path / "year=2024").chmod(0o000)
    try:
        got = year_partitions(tmp_path, [2022, 2023], max_year=2023)
        assert [p.name for p in got] == ["year=2022", "year=2023"]
        with pytest.raises(SealedYearError):
            year_partitions(tmp_path, [2023, 2024], max_year=2023)
        with pytest.raises(SealedYearError):
            year_partitions(tmp_path, [2022, 2023], max_year=2022)
    finally:
        (tmp_path / "year=2024").chmod(0o755)


# ------------------------------------------------------------------ loaders


def _write_d1(root: Path, records: Path, years: range) -> list[str]:
    names = ["Alpha", "Beta", "Gamma"]
    (records / "D1").mkdir(parents=True)
    with (records / "D1" / "articles.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["article", "total_top_views", "months_in_top", "cohort"])
        w.writerows([["Alpha", 1, 1, "A"], ["Beta", 1, 1, "A"], ["Gamma", 0, 0, "B"]])
    with (records / "D1" / "flags.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["article", "views_to_2022", "nonzero_days", "top3_month_share", "flags"])
        w.writerows([["Alpha", 1, 1, 0, ""], ["Beta", 1, 1, 0, "thin"], ["Gamma", 0, 0, 0, ""]])
    for year in years:
        days = [date(year, 1, 1) + timedelta(d) for d in range(366 if year % 4 == 0 else 365)]
        rows = {
            "article": [n for n in names for _ in days],
            "date": days * 3,
            "views": [i + d.day for i in range(3) for d in days],
        }
        folder = root / "D1" / f"year={year}"
        folder.mkdir(parents=True)
        pl.DataFrame(rows).with_columns(pl.col("views").cast(pl.Int32)).write_parquet(
            folder / "views.parquet"
        )
    return names


def test_load_d1_builds_the_matrix_in_list_order(tmp_path: Path) -> None:
    _write_d1(tmp_path / "data", tmp_path / "rec", range(2016, 2024))
    d = load_d1(tmp_path / "data", max_year=2022, records=tmp_path / "rec")
    assert d.counts.shape == (3, (date(2022, 12, 31) - date(2016, 1, 1)).days + 1)
    assert d.counts[1, 0] == 1 + 1  # Beta (i = 1) on 2016-01-01
    assert d.counts[2, d.day_index(date(2022, 3, 15))] == 2 + 15
    assert d.groups["cohort_B"].tolist() == [False, False, True]
    assert d.groups["flagged"].tolist() == [False, True, False]
    assert load_d1(tmp_path / "data", 2023, records=tmp_path / "rec").end == date(2023, 12, 31)


def test_d4_monthly_checkouts_are_spread_over_the_month(tmp_path: Path) -> None:
    sample = tmp_path / "sample"
    sample.mkdir()
    pl.DataFrame(
        {
            "key_id": [0, 1],
            "usageclass": ["Physical", "Digital"],
            "checkouttype": ["Horizon", "OverDrive"],
            "materialtype": ["BOOK", "EBOOK"],
            "title": ["T1", "T2"],
            "creator": ["C1", ""],
        }
    ).with_columns(pl.col("key_id").cast(pl.UInt32)).write_parquet(
        sample / "d4_sample_keys.parquet"
    )
    rows = [(k, y, m, 3 * (k + 1)) for k in (0, 1) for y in range(2016, 2024) for m in (2, 7)]
    pl.DataFrame(rows, schema=["key_id", "year", "month", "checkouts"], orient="row").write_parquet(
        sample / "d4_sample_monthly.parquet"
    )
    out = tmp_path / "parts"
    split_d4_sample(sample, out)
    d = load_d4(out, max_year=2022)
    feb = slice(d.day_index(date(2020, 2, 1)), d.day_index(date(2020, 3, 1)))
    assert d.counts[1, feb].sum() == pytest.approx(6.0)
    assert d.counts[1, feb][0] == pytest.approx(6 / 29)  # leap February
    assert d.counts[0, d.day_index(date(2020, 3, 1))] == 0
    assert d.resolution == "monthly" and d.groups["digital"].tolist() == [False, True]


def test_d4_sample_reads_only_training_years_for_the_population(tmp_path: Path) -> None:
    root = tmp_path / "D4"
    for year in range(2016, 2025):
        folder = root / f"year={year}"
        folder.mkdir(parents=True)
        if year == 2024:
            (folder / "checkouts.parquet").write_bytes(b"sealed, never read")
            continue
        titles = [f"t{year}", "shared"] if year < 2023 else ["only2023", "shared"]
        pl.DataFrame(
            {
                "usageclass": ["Physical"] * 2,
                "checkouttype": ["Horizon"] * 2,
                "materialtype": ["BOOK"] * 2,
                "checkoutyear": [year] * 2,
                "checkoutmonth": [1, 2],
                "checkouts": [1, 2],
                "title": titles,
                "isbn": [None, None],
                "creator": [None, " X "],
                "publicationyear": ["2000", "2000"],
            }
        ).write_parquet(folder / "checkouts.parquet")
    pop = d4_sample.population(root)
    assert "only2023" not in pop["title"].to_list()  # 2023 cannot shape the sample
    assert pop.height == 8  # t2016..t2022 plus "shared"
    assert pop.filter(pl.col("title") == "shared")["creator"].item() == "X"
    sample = d4_sample.draw(pop, size=3)
    assert sample.equals(d4_sample.draw(pop, size=3))  # fixed seed
    monthly = d4_sample.extract(root, sample)
    assert monthly["year"].max() == 2023


# ------------------------------------------------------------------ mapping


def _demand(n_days: int, seed: int = 0) -> Demand:
    rng = np.random.default_rng(seed)
    counts = rng.gamma(0.5, 20.0, (40, n_days))
    counts[:5, :400] = 0  # created later
    groups = {"cohort_A": np.arange(40) < 20, "cohort_B": np.arange(40) >= 20}
    return Demand(
        "D1", tuple(f"o{i}" for i in range(40)), date(2016, 1, 1), counts, "daily", groups
    )


def test_calibration_hits_the_target_median() -> None:
    d = _demand((date(2023, 12, 31) - date(2016, 1, 1)).days + 1)
    for setting, target in READ_TARGETS.items():
        s = default_scales(d, setting)
        rates = calibration_rates(d)
        for g in ("cohort_A", "cohort_B"):
            m = d.groups[g]
            assert np.median(rates[m] * s[m]) == pytest.approx(target)


def test_calibration_ignores_the_validation_year() -> None:
    full = _demand((date(2023, 12, 31) - date(2016, 1, 1)).days + 1)
    short = Demand(
        full.dataset, full.names, full.start, full.counts[:, :-365].copy(), "daily", full.groups
    )
    changed = full.counts.copy()
    changed[:, -365:] *= 50  # 2023 changes must not move the scale
    full2 = Demand(full.dataset, full.names, full.start, changed, "daily", full.groups)
    np.testing.assert_allclose(default_scales(short, "central"), default_scales(full2, "central"))


def test_reads_are_drawn_independently_each_year() -> None:
    """Identical demand in two years must not give identical reads: if every year reused one
    random stream, last year's noise would repeat and flatter the seasonal policy."""
    n_days = (date(2018, 1, 1) - date(2016, 1, 1)).days
    d = Demand(
        "D1",
        ("a", "b"),
        date(2016, 1, 1),
        np.full((2, n_days), 5.0),
        "daily",
        {"cohort_A": np.array([True, False]), "cohort_B": np.array([False, True])},
    )
    reads = to_reads(d, np.ones(2), "central")
    y2016, y2017 = reads[:, :365], reads[:, 366 : 366 + 365]  # 2016 is a leap year
    for row in range(2):  # per object: a reused stream repeats at least the first object exactly
        assert not np.array_equal(y2016[row], y2017[row])


def test_reads_of_a_year_do_not_depend_on_how_far_the_table_goes() -> None:
    full = _demand((date(2023, 12, 31) - date(2016, 1, 1)).days + 1)
    short = Demand(
        full.dataset, full.names, full.start, full.counts[:, :-365].copy(), "daily", full.groups
    )
    s = default_scales(short, "central")
    a, b = to_reads(short, s, "central"), to_reads(full, s, "central")
    np.testing.assert_array_equal(a, b[:, : a.shape[1]])
    assert (a[:5, :400] == 0).all()  # no demand, no reads


def test_reads_follow_the_scaled_demand_on_average() -> None:
    d = _demand(3000, seed=3)
    s = scales(d, 0.05, ("cohort_A", "cohort_B"))
    reads = to_reads(d, s, "central")
    expected = (s[:, None] * d.counts).sum()
    assert reads.sum() == pytest.approx(expected, rel=0.03)


# ------------------------------------------------------------------ sizes


def test_size_settings_match_the_measured_distributions() -> None:
    settings = size_settings(RECORDS)
    d2 = json.loads((RECORDS / "D2" / "size_calibration.json").read_text())
    fine = json.loads(
        (RECORDS / "D5" / "size_quantiles_IBMObjectStoreTrace004Part0.json").read_text()
    )
    qf, lo, hi = settings["low"]
    assert qf.mean(lo, hi) == pytest.approx(d2["mean_bytes_per_object"], rel=1e-6)
    assert float(qf(np.array([0.5]))[0]) == pytest.approx(d2["size_quantiles_by_object"]["p50"])
    qf, lo, hi = settings["central"]
    assert qf.mean(lo, hi) == pytest.approx(fine["mean_bytes_per_object"], rel=0.01)
    assert float(qf(np.array([0.5]))[0]) == pytest.approx(fine["quantiles"]["0.500"])
    qf, lo, hi = settings["high"]
    assert float(qf(np.array([0.75]))[0]) == pytest.approx(fine["quantiles"]["0.750"])


def test_sizes_are_reproducible_and_ordered_across_settings() -> None:
    u = draw_u(500, 1)
    np.testing.assert_array_equal(u, draw_u(500, 1))
    low, central, high = (sizes_for(u, s, RECORDS) for s in ("low", "central", "high"))
    order = np.argsort(u)
    for z in (low, central, high):
        assert (np.diff(z[order]) >= 0).all()  # same object keeps its rank
    assert (high >= central).all()


def test_trace_sizes_take_the_last_size_per_object(tmp_path: Path) -> None:
    trace = tmp_path / "t"
    trace.write_text(
        "1 REST.PUT.OBJECT a 100\n2 REST.GET.OBJECT a 100 0 99\n3 REST.GET.OBJECT b\n"
        "4 REST.PUT.OBJECT a 300\n5 REST.HEAD.OBJECT c 7\n"
    )
    sizes = object_sizes(trace)
    assert sorted(sizes.tolist()) == [7, 300]
    summary = summarise(sizes)
    assert summary["objects"] == 2 and summary["mean_bytes_per_object"] == 153.5
