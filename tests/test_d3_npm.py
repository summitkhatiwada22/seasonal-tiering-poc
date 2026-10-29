"""Tests for the npm (D3) fetcher against a fake registry and downloads API."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from sat.ingest import d1_wikipedia as d1
from sat.ingest import d3_npm
from sat.ingest.http import FetchError, Http


class Body:
    def __init__(self, obj: object) -> None:
        self._raw = json.dumps(obj).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> Body:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeNpm:
    def __init__(self, first_day: dict[str, date], names: list[str] | None = None) -> None:
        self.first_day = first_day
        self.names = names or []
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Body:
        url = request.full_url
        self.urls.append(url)
        if "registry.npmjs.org" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            offset, size = int(query["from"][0]), int(query["size"][0])
            chunk = self.names[offset : offset + size]
            return Body({"objects": [{"package": {"name": n}} for n in chunk]})
        m = re.search(r"/range/(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})/(.+)$", url)
        assert m, url
        start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
        package = urllib.parse.unquote(m.group(3))
        if package not in self.first_day:
            raise urllib.error.HTTPError(url, 404, "nf", None, None)  # type: ignore[arg-type]
        begin = max(start, self.first_day[package])
        days = [begin + timedelta(days=i) for i in range((end - begin).days + 1)]
        return Body(
            {
                "package": package,
                "downloads": [{"day": d.isoformat(), "downloads": 10} for d in days],
            }
        )


def client(fake: FakeNpm) -> Http:
    return Http("ua", opener=fake, min_interval=0, sleep=lambda s: None)


def test_scoped_package_url_keeps_slash_and_at() -> None:
    url = d3_npm.range_url("@babel/core", date(2020, 1, 1), date(2020, 12, 31))
    assert url.endswith("/2020-01-01:2020-12-31/@babel/core")


def test_late_start_is_allowed_but_gaps_and_truncation_are_not() -> None:
    start, end = date(2020, 1, 1), date(2020, 1, 10)

    def body(days: list[int]) -> dict[str, object]:
        return {"downloads": [{"day": f"2020-01-{d:02d}", "downloads": 1} for d in days]}

    assert len(d3_npm.parse_range(body(list(range(4, 11))), start, end)) == 7  # package born Jan 4
    with pytest.raises(FetchError, match="gaps"):
        d3_npm.parse_range(body([1, 2, 3, 4, 5]), start, end)  # end missing: truncated
    with pytest.raises(FetchError, match="gaps"):
        d3_npm.parse_range(body([1, 2, 4, 5, 6, 7, 8, 9, 10]), start, end)  # hole
    with pytest.raises(FetchError):
        d3_npm.parse_range({"error": "x"}, start, end)


def test_fetch_package_merges_year_chunks_and_unknown_is_empty() -> None:
    fake = FakeNpm({"left-pad": date(2017, 6, 1)})
    got = d3_npm.fetch_package_downloads(
        client(fake), "left-pad", date(2016, 1, 1), date(2018, 12, 31), 1
    )
    assert min(got) == date(2017, 6, 1) and max(got) == date(2018, 12, 31)
    assert len(got) == (date(2018, 12, 31) - date(2017, 6, 1)).days + 1
    assert (
        d3_npm.fetch_package_downloads(
            client(fake), "ghost", date(2016, 1, 1), date(2016, 12, 31), 1
        )
        == {}
    )


def test_search_returns_requested_count_and_fails_when_short() -> None:
    names = [f"pkg{i}" for i in range(600)]
    assert d3_npm.search_packages(client(FakeNpm({}, names)), 300) == names[:300]
    with pytest.raises(FetchError, match="only"):
        d3_npm.search_packages(client(FakeNpm({}, names[:10])), 50)
    with pytest.raises(ValueError):
        d3_npm.search_packages(client(FakeNpm({}, names)), 10**6)


def test_list_is_never_redrawn_then_fetch_flags_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNpm({"a": date(2016, 1, 1), "b": date(2019, 1, 1)}, ["a", "b"])
    original = Http.__init__

    def init(self: Http, user_agent: str, **kwargs: object) -> None:
        kwargs.update(opener=fake, sleep=lambda s: None, min_interval=0)
        original(self, user_agent, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Http, "__init__", init)
    args = ["--data-dir", str(tmp_path), "--contact", "a@b.c"]
    assert d3_npm.main(["list", *args, "--packages", "2"]) == 0
    first = (tmp_path / "interim" / "D3" / "packages.csv").read_text(encoding="utf-8")
    assert d3_npm.main(["list", *args, "--packages", "1"]) == 0
    assert (tmp_path / "interim" / "D3" / "packages.csv").read_text(encoding="utf-8") == first
    assert "not redrawn" in capsys.readouterr().out
    assert d3_npm.main(["fetch", *args]) == 0
    assert d3_npm.main(["flags", "--data-dir", str(tmp_path)]) == 0
    assert d3_npm.main(["build", "--data-dir", str(tmp_path)]) == 0
    frame = pl.read_parquet(tmp_path / "processed" / "D3" / "year=2016" / "views.parquet")
    assert set(frame.columns) == {"package", "date", "views"}
    days_2016 = 366
    assert frame.height == 2 * days_2016
    assert frame.filter(pl.col("package") == "b")["views"].sum() == 0  # not yet published
    assert d1.read_done(tmp_path / "raw" / "D3" / "downloads.jsonl") == {"a", "b"}


def test_from_file_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = tmp_path / "names.txt"
    names.write_text("react\n\n@babel/core\n", encoding="utf-8")
    assert (
        d3_npm.main(
            [
                "list",
                "--data-dir",
                str(tmp_path / "d"),
                "--contact",
                "a@b.c",
                "--from-file",
                str(names),
            ]
        )
        == 0
    )
    assert d3_npm.read_list(tmp_path / "d" / "interim" / "D3" / "packages.csv") == [
        "react",
        "@babel/core",
    ]
