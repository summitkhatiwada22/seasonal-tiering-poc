from __future__ import annotations

from pathlib import Path

import pytest

from sat.prices import PriceSheetError, load_all, load_price_sheet

PRICES_DIR = Path(__file__).resolve().parents[1] / "configs" / "prices"


def test_all_three_clouds_load() -> None:
    sheets = load_all(PRICES_DIR)
    assert set(sheets) == {"aws", "gcs", "azure"}


def test_every_sheet_has_a_compile_date_and_currency() -> None:
    for sheet in load_all(PRICES_DIR).values():
        assert sheet.as_of.year >= 2026
        assert sheet.currency == "USD"


def test_storage_price_never_rises_towards_colder_tiers() -> None:
    for sheet in load_all(PRICES_DIR).values():
        prices = [sheet.get(tier, "storage_usd_per_gb_month") for tier in sheet.tier_order]
        assert prices == sorted(prices, reverse=True), sheet.cloud


def test_hot_tier_has_no_retrieval_fee_or_restore_wait() -> None:
    for sheet in load_all(PRICES_DIR).values():
        hot = sheet.tier_order[0]
        assert sheet.get(hot, "retrieval_usd_per_gb") == 0.0
        assert sheet.get(hot, "restore_hours") == 0


def test_aws_golden_values() -> None:
    aws = load_all(PRICES_DIR)["aws"]
    assert aws.get("standard", "storage_usd_per_gb_month") == pytest.approx(0.023)
    assert aws.get("deep_archive", "storage_usd_per_gb_month") == pytest.approx(0.00099)
    assert aws.get("deep_archive", "min_storage_days") == 180
    assert aws.get("deep_archive", "retrieval_usd_per_gb") == pytest.approx(0.02)
    # The "23x" gap between Standard and Deep Archive quoted by several sources.
    ratio = aws.get("standard", "storage_usd_per_gb_month") / aws.get(
        "deep_archive", "storage_usd_per_gb_month"
    )
    assert ratio == pytest.approx(23.2, abs=0.1)


def test_gcs_archive_has_a_365_day_minimum() -> None:
    gcs = load_all(PRICES_DIR)["gcs"]
    assert gcs.get("archive", "min_storage_days") == 365


def test_azure_matches_owner_screenshot_2026_10_29() -> None:
    azure = load_all(PRICES_DIR)["azure"]
    assert azure.get("hot", "storage_usd_per_gb_month") == pytest.approx(0.0184)
    assert azure.get("cool", "storage_usd_per_gb_month") == pytest.approx(0.010)
    assert azure.get("cold", "storage_usd_per_gb_month") == pytest.approx(0.0036)
    # Archive was 0.00099 (an AWS figure) before the screenshot corrected it.
    assert azure.get("archive", "storage_usd_per_gb_month") == pytest.approx(0.002)
    assert azure.get("archive", "min_storage_days") == 180
    assert azure.get("cold", "min_storage_days") == 90
    assert azure.get("cool", "retrieval_usd_per_gb") == pytest.approx(0.01)
    assert azure.get("cold", "retrieval_usd_per_gb") == pytest.approx(0.03)
    assert azure.get("archive", "retrieval_usd_per_gb") == pytest.approx(0.02)
    assert azure.get("archive", "restore_hours") == 15
    # Operations are quoted per 10,000; the sheet stores per 1,000 (archive read $5 per 10,000).
    assert azure.get("archive", "get_per_1000") == pytest.approx(0.5)
    assert azure.get("hot", "put_per_1000") == pytest.approx(0.005)


def test_unverified_values_are_listed_so_nobody_forgets_them() -> None:
    gcs = load_all(PRICES_DIR)["gcs"]
    unverified = gcs.unverified()
    # Storage, retrieval and minimum durations were verified against Google's page in Phase 1.
    assert "standard.storage_usd_per_gb_month" not in unverified
    assert "coldline.storage_usd_per_gb_month" not in unverified
    # Facts the page extract did not state stay flagged until someone checks them.
    assert "archive.restore_hours" in unverified


def test_gcs_matches_google_official_page_checked_2026_10_29() -> None:
    gcs = load_all(PRICES_DIR)["gcs"]
    expected = {
        ("standard", "storage_usd_per_gb_month"): 0.020,
        ("nearline", "storage_usd_per_gb_month"): 0.010,
        ("coldline", "storage_usd_per_gb_month"): 0.004,
        ("archive", "storage_usd_per_gb_month"): 0.0012,
        ("nearline", "retrieval_usd_per_gb"): 0.01,
        ("coldline", "retrieval_usd_per_gb"): 0.02,
        ("archive", "retrieval_usd_per_gb"): 0.05,
        ("nearline", "min_storage_days"): 30,
        ("coldline", "min_storage_days"): 90,
    }
    for (tier, field), value in expected.items():
        assert gcs.get(tier, field) == pytest.approx(value), (tier, field)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    return path


GOOD_TIER = """
    storage_usd_per_gb_month: {value: 0.02, status: unverified, source: memory}
    retrieval_usd_per_gb: {value: 0, status: unverified, source: memory}
    min_storage_days: {value: 0, status: unverified, source: memory}
    min_billable_object_kb: {value: 0, status: unverified, source: memory}
    per_object_overhead_kb: {value: 0, status: unverified, source: memory}
    restore_hours: {value: 0, status: unverified, source: memory}
"""


def _sheet(tier_block: str = GOOD_TIER, as_of: str = "as_of: 2026-10-29") -> str:
    return f"cloud: x\nregion: r\ncurrency: USD\n{as_of}\ntier_order: [t]\ntiers:\n  t:{tier_block}"


def test_a_valid_minimal_sheet_loads(tmp_path: Path) -> None:
    sheet = load_price_sheet(_write(tmp_path, _sheet()))
    assert sheet.get("t", "storage_usd_per_gb_month") == pytest.approx(0.02)


def test_negative_price_is_rejected(tmp_path: Path) -> None:
    bad = GOOD_TIER.replace("value: 0.02", "value: -0.02")
    with pytest.raises(PriceSheetError, match="negative"):
        load_price_sheet(_write(tmp_path, _sheet(bad)))


def test_missing_as_of_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PriceSheetError, match="as_of"):
        load_price_sheet(_write(tmp_path, _sheet(as_of="")))


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    bad = GOOD_TIER.replace("status: unverified, source: memory}", "status: maybe, source: x}", 1)
    with pytest.raises(PriceSheetError, match="status"):
        load_price_sheet(_write(tmp_path, _sheet(bad)))


def test_sourced_value_without_a_url_is_rejected(tmp_path: Path) -> None:
    bad = GOOD_TIER.replace(
        "status: unverified, source: memory}", "status: sourced, source: me}", 1
    )
    with pytest.raises(PriceSheetError, match="URL"):
        load_price_sheet(_write(tmp_path, _sheet(bad)))


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    bad = "\n".join(line for line in GOOD_TIER.splitlines() if "restore_hours" not in line)
    with pytest.raises(PriceSheetError, match="restore_hours"):
        load_price_sheet(_write(tmp_path, _sheet(bad)))


def test_aws_glacier_flexible_matches_owner_calculator_2026_10_30() -> None:
    """10,000 GB in 16 MB objects plus 1,000 GB standard retrieval came to $46.18 a month."""
    aws = load_all(PRICES_DIR)["aws"]
    gb_stored, retrieved_gb = 10_000, 1_000
    objects = gb_stored * 1024 / 16  # the calculator counts in binary units
    overhead_kb = aws.get("glacier_flexible", "per_object_overhead_kb")
    assert overhead_kb == 40  # 32 KB archive metadata + 8 KB name index in Standard
    glacier_gb = objects * (overhead_kb - 8) / 1024 / 1024
    standard_gb = objects * 8 / 1024 / 1024
    total = (
        gb_stored * aws.get("glacier_flexible", "storage_usd_per_gb_month")
        + glacier_gb * aws.get("glacier_flexible", "storage_usd_per_gb_month")
        + standard_gb * aws.get("standard", "storage_usd_per_gb_month")
        + retrieved_gb * aws.get("glacier_flexible", "retrieval_usd_per_gb")
    )
    assert round(total, 2) == 46.18
