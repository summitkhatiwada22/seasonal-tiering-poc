"""Tests for size calibration, resumable file download, manifests and the quality report."""

from __future__ import annotations

import bz2
import io
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from sat.ingest import calibration, files, quality
from sat.ingest.http import FetchError
from sat.ingest.manifest import record, verify_manifest


def test_mediacounts_average_size_and_weighting() -> None:
    lines = [
        "/a.jpg\t1000\t10\t0\n",  # 100 bytes per transfer, 10 transfers
        "/b.jpg\t5000000\t1\t0\n",  # 5 MB, 1 transfer
        "/c.jpg\t0\t0\t0\n",  # no transfers: skipped
        "garbage\n",
    ]
    result = calibration.summarise_mediacounts(lines)
    assert result["objects"] == 2 and result["skipped_lines"] == 2
    by_object = result["size_quantiles_by_object"]
    assert 90 < by_object["p01"] < 110 and by_object["p99"] > 4_000_000
    assert result["size_quantiles_by_weight"]["p50"] < 110  # most transfers are the small file
    with pytest.raises(FetchError, match="no usable lines"):
        calibration.summarise_mediacounts(["x\ty\tz\n"])


def test_ibm_trace_summary() -> None:
    lines = [
        "1000 REST.PUT.OBJECT obj1 4096",
        "1001 REST.GET.OBJECT obj1 4096",
        "1002 REST.GET.OBJECT obj1 4096 0 4095",
        "1003 REST.GET.OBJECT obj2 100",
        "1004 REST.DELETE.OBJECT obj2",
    ]
    result = calibration.summarise_ibm_trace(lines)
    assert result["get_requests"] == 3 and result["distinct_objects_read"] == 2
    assert result["share_of_gets_to_objects_read_twice_or_more"] == pytest.approx(2 / 3)
    assert result["object_size"]["objects"] == 2
    with pytest.raises(FetchError, match="do not match"):
        calibration.summarise_ibm_trace(["one", "two", "three"])


class FakeFile:
    def __init__(
        self, payload: bytes, honour_range: bool = True, fail_after: int | None = None
    ) -> None:
        self.payload = payload
        self.honour_range = honour_range
        self.fail_after = fail_after
        self.ranges: list[str | None] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> object:
        start = 0
        header = request.headers.get("Range")
        self.ranges.append(header)
        if header and self.honour_range:
            start = int(header.split("=")[1].rstrip("-"))
        data = self.payload[start:]
        status = 206 if start else 200
        if self.fail_after is not None:
            data_cut = data[: self.fail_after]
            self.fail_after = None
            return _Stream(data_cut, status, total=len(data))
        return _Stream(data, status, total=len(data))


class _Stream(io.BytesIO):
    def __init__(self, data: bytes, status: int, total: int) -> None:
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(total)}

    def __enter__(self) -> _Stream:
        return self


def test_download_resumes_with_range(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 5000
    fake = FakeFile(payload, fail_after=300_000)
    dest = tmp_path / "f.bin"
    files.download_resumable("http://x/f", dest, "ua", opener=fake, sleep=lambda s: None)
    assert dest.read_bytes() == payload and not dest.with_name("f.bin.part").exists()
    assert fake.ranges[0] is None and fake.ranges[1] == "bytes=300000-"


def test_download_restarts_if_server_ignores_range(tmp_path: Path) -> None:
    payload = b"abcdefghij" * 100_000
    fake = FakeFile(payload, honour_range=False, fail_after=123_456)
    dest = tmp_path / "g.bin"
    files.download_resumable("http://x/g", dest, "ua", opener=fake, sleep=lambda s: None)
    assert dest.read_bytes() == payload


def test_download_checks_expected_size(tmp_path: Path) -> None:
    fake = FakeFile(b"short")
    with pytest.raises(FetchError, match="gave up"):
        files.download_resumable(
            "http://x/h",
            tmp_path / "h.bin",
            "ua",
            expected_bytes=999,
            opener=fake,
            sleep=lambda s: None,
            retries=1,
        )
    assert not (tmp_path / "h.bin").exists()


def test_download_permanent_error(tmp_path: Path) -> None:
    def refuse(request: urllib.request.Request, timeout: float) -> object:
        raise urllib.error.HTTPError(request.full_url, 403, "no", None, None)  # type: ignore[arg-type]

    with pytest.raises(FetchError, match="403"):
        files.download_resumable("http://x", tmp_path / "z", "ua", opener=refuse)


def test_calibrate_d2_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = b"/a.jpg\t1000\t10\n/b.png\t8000\t2\n"
    payload = bz2.compress(text)
    monkeypatch.setattr(calibration, "D2_BYTES", len(payload))
    monkeypatch.setattr(
        files, "default_opener", lambda request, timeout: _Stream(payload, 200, len(payload))
    )
    assert calibration.main(["d2", "--data-dir", str(tmp_path), "--contact", "a@b.c"]) == 0
    summary = json.loads((tmp_path / "processed" / "D2" / "size_calibration.json").read_text())
    assert summary["objects"] == 2
    assert verify_manifest(tmp_path / "manifests" / "D2.csv", tmp_path).ok


def test_verify_manifest_detects_change_and_loss(tmp_path: Path) -> None:
    data = tmp_path / "raw" / "x.bin"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"one")
    manifest = tmp_path / "manifests" / "X.csv"
    record(manifest, "X", "u", data, base=tmp_path)
    assert verify_manifest(manifest, tmp_path).ok
    data.write_bytes(b"two")
    assert verify_manifest(manifest, tmp_path).changed == ["raw/x.bin"]
    data.unlink()
    assert verify_manifest(manifest, tmp_path).missing == ["raw/x.bin"]


def _write_daily(
    base: Path, dataset: str, key: str, names: list[str], start: date, end: date
) -> None:
    all_days = np.arange(
        np.datetime64(start.isoformat()), np.datetime64(end.isoformat()) + np.timedelta64(1, "D")
    )
    for year in range(start.year, end.year + 1):
        days = np.array([d for d in all_days if int(str(d)[:4]) == year])
        frame = pl.DataFrame(
            {
                key: np.repeat(np.array(names), len(days)),
                "date": np.tile(days, len(names)),
                "views": np.tile(np.arange(len(days)) + 1, len(names)).astype(np.int32),
            }
        )
        target = base / "processed" / dataset / f"year={year}" / "views.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(target)


def test_quality_daily_pass_and_fail(tmp_path: Path) -> None:
    start, end = date(2020, 1, 1), date(2021, 12, 31)
    _write_daily(tmp_path, "D1", "article", ["Cat", "Dog"], start, end)
    listing = tmp_path / "interim" / "D1" / "articles.csv"
    listing.parent.mkdir(parents=True)
    listing.write_text("article,total_top_views,months_in_top,cohort\nCat,1,1,A\nDog,1,1,A\n")
    flags = tmp_path / "interim" / "D1" / "flags.csv"
    flags.write_text(
        "article,views_to_2022,nonzero_days,top3_month_share,flags\nCat,1,1,0.1,\nDog,1,1,0.9,bursty\n"
    )
    views = tmp_path / "raw" / "D1" / "views.jsonl"
    views.parent.mkdir(parents=True)
    views.write_text("{}\n")
    record(tmp_path / "manifests" / "D1.csv", "D1", "api", views, base=tmp_path)
    checks = quality.check_daily(tmp_path, "D1", "article", start, end, listing, flags)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    listing.write_text(
        "article,total_top_views,months_in_top,cohort\nCat,1,1,A\nDog,1,1,A\nEmu,1,1,A\n"
    )
    failed = [
        c.name
        for c in quality.check_daily(tmp_path, "D1", "article", start, end, listing, flags)
        if not c.ok
    ]
    assert failed == ["every listed item downloaded"]
    wrong_end = quality.check_daily(
        tmp_path, "D1", "article", start, date(2022, 12, 31), listing, flags
    )
    assert not wrong_end[0].ok


def test_quality_cli_writes_reports(tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = quality.main(["--data-dir", str(tmp_path / "empty"), "--out", str(out), "--only", "D2"])
    assert code == 1  # nothing downloaded: a failing report, not a crash
    assert "FAIL" in (out / "quality_report.md").read_text(encoding="utf-8")
    assert json.loads((out / "quality_report.json").read_text())["D2"][0]["ok"] is False
