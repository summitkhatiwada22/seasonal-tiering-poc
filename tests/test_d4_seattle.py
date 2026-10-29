"""Tests for the Seattle (D4) fetcher against a fake Socrata server."""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from sat.ingest import d4_seattle as d4
from sat.ingest.http import FetchError, Http
from sat.ingest.manifest import verify_manifest


class Body:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> Body:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeSocrata:
    def __init__(self, rows_by_year: dict[int, int], text_year: bool = True) -> None:
        self.rows_by_year = rows_by_year
        self.text_year = text_year
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Body:
        url = request.full_url
        self.urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        where = query.get("$where", [""])[0]
        year = int(where.split("=")[1].strip("'")) if where else None
        quoted = "'" in where
        if year is not None and quoted != self.text_year:
            raise urllib.error.HTTPError(url, 400, "type mismatch", Message(), io.BytesIO(b""))
        total = sum(self.rows_by_year.values()) if year is None else self.rows_by_year.get(year, 0)
        if query["$select"][0] == "count(*)":
            return Body(json.dumps([{"count": str(total)}]).encode())
        assert year is not None
        offset, limit = int(query["$offset"][0]), int(query["$limit"][0])
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(d4.COLUMNS)
        for i in range(offset, min(total, offset + limit)):
            writer.writerow(
                [
                    "Physical",
                    "Horizon",
                    "BOOK",
                    year,
                    1 + i % 12,
                    2 + i,
                    f"T{i}, vol 1",
                    "",
                    "A",
                    "2000",
                ]
            )
        return Body(buffer.getvalue().encode())


@pytest.fixture(autouse=True)
def small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d4, "PAGE_ROWS", 4)


def client(fake: FakeSocrata) -> Http:
    return Http("ua", opener=fake, min_interval=0, sleep=lambda s: None)


def test_year_style_detected_for_text_and_numeric_fields() -> None:
    assert d4.detect_year_style(client(FakeSocrata({2016: 5}, text_year=True))) is True
    assert d4.detect_year_style(client(FakeSocrata({2016: 5}, text_year=False))) is False


def test_parse_count_rejects_nonsense() -> None:
    with pytest.raises(FetchError):
        d4.parse_count({"error": "x"})


def test_fetch_resume_build_and_manifest(tmp_path: Path) -> None:
    fake = FakeSocrata({2016: 10, 2017: 3})
    http = client(fake)
    manifest = tmp_path / "manifests" / "D4.csv"
    written, total = d4.fetch_year(
        http, tmp_path, 2016, True, manifest, max_pages=1, progress=lambda s: None
    )
    assert (written, total) == (1, 10)  # trial run: only the first of 3 pages
    written, _ = d4.fetch_year(http, tmp_path, 2016, True, manifest, progress=lambda s: None)
    assert written == 2  # resumed: pages 2 and 3 only
    d4.fetch_year(http, tmp_path, 2017, True, manifest, progress=lambda s: None)
    result = d4.build_year(tmp_path, 2016)
    assert result["rows"] == 10
    frame = pl.read_parquet(tmp_path / "processed" / "D4" / "year=2016" / "checkouts.parquet")
    assert frame.height == 10 and frame["title"][0] == "T0, vol 1"  # commas survive
    assert verify_manifest(manifest, tmp_path).ok


def test_short_page_is_an_error(tmp_path: Path) -> None:
    fake = FakeSocrata({2016: 8})
    original = fake.__call__

    def short(request: urllib.request.Request, timeout: float) -> Body:
        body = original(request, timeout)
        raw = body.read()
        if b"count" in raw:
            return Body(raw)
        return Body(b"\n".join(raw.split(b"\n")[:-2]) + b"\n")  # drop a row

    with pytest.raises(FetchError, match="expected"):
        d4.fetch_year(
            Http("ua", opener=short, min_interval=0, sleep=lambda s: None),
            tmp_path,
            2016,
            True,
            progress=lambda s: None,
        )


def test_changed_row_count_is_refused(tmp_path: Path) -> None:
    http = client(FakeSocrata({2016: 8}))
    d4.fetch_year(http, tmp_path, 2016, True, progress=lambda s: None)
    with pytest.raises(FetchError, match="changed the row count"):
        d4.fetch_year(client(FakeSocrata({2016: 9})), tmp_path, 2016, True, progress=lambda s: None)


def test_missing_columns_detected() -> None:
    with pytest.raises(FetchError, match="missing"):
        d4.check_header(["title"])


def test_build_refuses_incomplete_year(tmp_path: Path) -> None:
    http = client(FakeSocrata({2016: 10}))
    d4.fetch_year(http, tmp_path, 2016, True, max_pages=1, progress=lambda s: None)
    with pytest.raises(FetchError, match="pages on disk"):
        d4.build_year(tmp_path, 2016)


def test_cli_inspect_and_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSocrata({2016: 5})
    monkeypatch.setattr("sat.ingest.http.default_opener", fake)
    monkeypatch.setattr(Http, "__init__", _patched_init(fake), raising=True)
    assert (
        d4.main(["inspect", "--data-dir", str(tmp_path), "--contact", "a@b.c", "--years", "2016"])
        == 0
    )
    assert "rows on server: 5" in capsys.readouterr().out
    assert d4.main(["status", "--data-dir", str(tmp_path)]) == 0


def _patched_init(fake: Any) -> Any:
    original = Http.__init__

    def init(self: Http, user_agent: str, **kwargs: Any) -> None:
        kwargs.update(opener=fake, sleep=lambda s: None, min_interval=0)
        original(self, user_agent, **kwargs)

    return init
