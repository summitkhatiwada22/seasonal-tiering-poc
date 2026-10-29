"""Tests for the Wikipedia (D1) fetcher, using a fake API and no internet."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from sat.ingest import d1_wikipedia as d1
from sat.ingest.http import FetchError, Http


class FakeWikimedia:
    """Answers the two endpoints we use from in-memory tables."""

    def __init__(
        self,
        top: dict[tuple[int, int], list[tuple[str, int]]],
        views: dict[str, dict[date, int]],
        max_span_days: int = 10_000,
    ) -> None:
        self.top = top
        self.views = views
        self.max_span_days = max_span_days
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        import io
        import urllib.error
        from email.message import Message

        url = request.full_url
        self.urls.append(url)
        if "/top/" in url:
            m = re.search(r"/(\d{4})/(\d{2})/all-days", url)
            assert m
            rows = self.top.get((int(m.group(1)), int(m.group(2))))
            if rows is None:
                raise urllib.error.HTTPError(url, 404, "nf", Message(), io.BytesIO(b""))
            items = [{"article": a, "views": v, "rank": i + 1} for i, (a, v) in enumerate(rows)]
            return _Body({"items": [{"articles": items}]})
        m = re.search(r"/user/([^/]+)/daily/(\d{8})/(\d{8})", url)
        assert m, url
        article = urllib.parse.unquote(m.group(1))
        start = date(int(m.group(2)[:4]), int(m.group(2)[4:6]), int(m.group(2)[6:]))
        end = date(int(m.group(3)[:4]), int(m.group(3)[4:6]), int(m.group(3)[6:]))
        if article not in self.views:
            raise urllib.error.HTTPError(url, 404, "nf", Message(), io.BytesIO(b""))
        days = sorted(d for d in self.views[article] if start <= d <= end)
        if (end - start).days + 1 > self.max_span_days:
            days = days[: self.max_span_days]  # simulate a silently cut-off answer
        items = [
            {"article": article, "timestamp": f"{d:%Y%m%d}00", "views": self.views[article][d]}
            for d in days
        ]
        return _Body({"items": items})


class _Body:
    def __init__(self, obj: Any) -> None:
        self._raw = json.dumps(obj).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def client(fake: FakeWikimedia) -> Http:
    return Http("ua", opener=fake, min_interval=0, sleep=lambda s: None)


def test_is_article_filters_front_page_and_namespaces() -> None:
    assert d1.is_article("Albert_Einstein")
    assert d1.is_article("Star_Wars:_Episode_IV")  # a colon alone does not exclude
    assert not d1.is_article("Main_Page")
    assert not d1.is_article("Special:Search")
    assert not d1.is_article("Wikipedia:Featured_pictures")
    assert not d1.is_article("Talk:Cat")
    assert not d1.is_article("-")


def test_month_range_crosses_year_end() -> None:
    assert list(d1.month_range((2022, 11), (2023, 2))) == [
        (2022, 11),
        (2022, 12),
        (2023, 1),
        (2023, 2),
    ]


def test_article_list_ranking_filter_and_cache(tmp_path: Path) -> None:
    top = {
        (2020, 1): [("Main_Page", 900), ("Cat", 50), ("Dog", 40), ("Special:Search", 800)],
        (2020, 2): [("Dog", 45), ("Emu", 10), ("Cat", 5)],
    }
    fake = FakeWikimedia(top, {})
    http = client(fake)
    months = [(2020, 1), (2020, 2)]
    selection = d1.build_article_list(http, tmp_path, n=2, months=months)
    rows = selection.rows
    assert [r.article for r in rows] == ["Dog", "Cat"]  # Dog 85, Cat 55, Emu 10
    assert rows[0].total_top_views == 85 and rows[0].months_in_top == 2
    assert selection.missing_months == []
    first_calls = len(fake.urls)
    again = d1.build_article_list(http, tmp_path, n=2, months=months)
    assert again.rows == rows and len(fake.urls) == first_calls  # second run used the cache


def test_selection_refuses_months_after_cutoff(tmp_path: Path) -> None:
    http = client(FakeWikimedia({}, {}))
    with pytest.raises(ValueError, match="after December 2022"):
        d1.build_article_list(http, tmp_path, months=[(2023, 1)])


def test_a_missing_month_is_skipped_and_reported(tmp_path: Path) -> None:
    top = {(2020, 6): [("Cat", 5)], (2020, 8): [("Cat", 7)]}  # July 2020 is missing
    http = client(FakeWikimedia(top, {}))
    months = [(2020, 6), (2020, 7), (2020, 8)]
    selection = d1.build_article_list(http, tmp_path, months=months)
    assert selection.missing_months == [(2020, 7)]
    assert selection.rows == [d1.ArticleRow("Cat", 12, 2)]


def test_too_many_missing_months_is_an_error(tmp_path: Path) -> None:
    http = client(FakeWikimedia({}, {}))
    with pytest.raises(FetchError, match="2020-05"):
        d1.build_article_list(http, tmp_path, months=[(2020, 5)], max_missing=0)
    with pytest.raises(FetchError, match="too many"):  # no data at all is never acceptable
        d1.build_article_list(http, tmp_path, months=[(2020, 5), (2020, 6)], max_missing=1)


def test_article_list_roundtrip(tmp_path: Path) -> None:
    rows = [d1.ArticleRow("A", 5, 1), d1.ArticleRow("B_(x)", 3, 2)]
    path = tmp_path / "a.csv"
    d1.write_article_list(path, rows)
    assert d1.read_article_list(path) == rows


def test_article_url_encodes_special_characters() -> None:
    url = d1.article_url("AC/DC", date(2020, 1, 1), date(2020, 12, 31))
    assert "AC%2FDC" in url and url.endswith("/20200101/20201231")


def test_parse_views_rejects_bad_answers() -> None:
    start, end = date(2020, 1, 1), date(2020, 1, 31)
    ok = {"items": [{"timestamp": "2020010100", "views": 4}]}
    assert d1.parse_views(ok, start, end) == {date(2020, 1, 1): 4}
    with pytest.raises(FetchError, match="outside"):
        d1.parse_views({"items": [{"timestamp": "2020030100", "views": 1}]}, start, end)
    twice = {"items": [{"timestamp": "2020010100", "views": 1}] * 2}
    with pytest.raises(FetchError, match="twice"):
        d1.parse_views(twice, start, end)
    with pytest.raises(FetchError, match="negative"):
        d1.parse_views({"items": [{"timestamp": "2020010100", "views": -1}]}, start, end)


def test_year_chunks() -> None:
    chunks = d1.year_chunks(date(2016, 1, 1), date(2018, 6, 30), 2)
    assert chunks == [(date(2016, 1, 1), date(2017, 12, 31)), (date(2018, 1, 1), date(2018, 6, 30))]
    with pytest.raises(ValueError):
        d1.year_chunks(date(2020, 1, 1), date(2019, 1, 1), 1)


def full_year(year: int, views: int = 1) -> dict[date, int]:
    out: dict[date, int] = {}
    day = date(year, 1, 1)
    while day.year == year:
        out[day] = views
        day = date.fromordinal(day.toordinal() + 1)
    return out


def test_detect_span_uses_longest_complete_answer() -> None:
    series: dict[date, int] = {}
    for y in range(2016, 2026):
        series.update(full_year(y))
    http = client(FakeWikimedia({}, {d1.CALIBRATION_ARTICLE: series}))
    assert d1.detect_span_years(http, date(2016, 1, 1), date(2025, 12, 31)) == 10
    capped = FakeWikimedia({}, {d1.CALIBRATION_ARTICLE: series}, max_span_days=366)
    assert d1.detect_span_years(client(capped), date(2016, 1, 1), date(2025, 12, 31)) == 1


def test_fetch_all_resume_and_missing_days(tmp_path: Path) -> None:
    start, end = date(2020, 1, 1), date(2021, 12, 31)
    views = {
        "Cat": {date(2020, 1, 2): 5, date(2021, 3, 3): 7},
        "Dog": {date(2020, 6, 6): 1},
    }
    fake = FakeWikimedia({}, views)
    out = tmp_path / "views.jsonl"
    msgs: list[str] = []
    first = d1.fetch_all(client(fake), ["Cat"], out, start, end, 1, workers=2, progress=msgs.append)
    assert first.done == 1 and first.skipped == 0
    calls_after_first = len(fake.urls)
    second = d1.fetch_all(
        client(fake), ["Cat", "Dog", "Ghost"], out, start, end, 1, workers=2, progress=msgs.append
    )
    assert second.skipped == 1 and second.done == 2  # Ghost has no data: 404 means zero views
    assert len(fake.urls) == calls_after_first + 2 * 2  # Cat was not fetched again
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert {x["article"] for x in lines} == {"Cat", "Dog", "Ghost"}
    assert next(x for x in lines if x["article"] == "Ghost")["views"] == {}


def test_fetch_all_recovers_from_half_written_line(tmp_path: Path) -> None:
    start, end = date(2020, 1, 1), date(2020, 12, 31)
    fake = FakeWikimedia({}, {"Cat": {date(2020, 5, 5): 3}, "Dog": {date(2020, 5, 6): 4}})
    out = tmp_path / "views.jsonl"
    d1.fetch_all(client(fake), ["Cat"], out, start, end, 1, progress=lambda m: None)
    with out.open("a", encoding="utf-8") as handle:
        handle.write('{"article":"Dog","vi')  # simulated crash mid-write
    summary = d1.fetch_all(
        client(fake), ["Cat", "Dog"], out, start, end, 1, progress=lambda m: None
    )
    assert summary.done == 1 and summary.skipped == 1
    assert d1._read_done(out) == {"Cat", "Dog"}


def test_fetch_all_refuses_changed_settings(tmp_path: Path) -> None:
    fake = FakeWikimedia({}, {"Cat": {}})
    out = tmp_path / "views.jsonl"
    d1.fetch_all(
        client(fake), ["Cat"], out, date(2020, 1, 1), date(2020, 12, 31), 1, progress=print
    )
    with pytest.raises(FetchError, match="different settings"):
        d1.fetch_all(client(fake), ["Cat"], out, date(2019, 1, 1), date(2020, 12, 31), 1)


def test_build_parquet_fills_zeros_and_splits_years(tmp_path: Path) -> None:
    start, end = date(2020, 12, 30), date(2021, 1, 2)
    jsonl = tmp_path / "views.jsonl"
    rows = [
        {"article": "Cat", "views": {"2020-12-31": 5, "2021-01-01": 9}},
        {"article": "Ant", "views": {}},
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    summary = d1.build_parquet(jsonl, tmp_path / "out", start, end)
    assert summary["articles"] == 2 and summary["days"] == 4
    y2020 = pl.read_parquet(tmp_path / "out" / "year=2020" / "views.parquet")
    y2021 = pl.read_parquet(tmp_path / "out" / "year=2021" / "views.parquet")
    assert y2020.height == 4 and y2021.height == 4  # 2 articles x 2 days each
    cat = y2020.filter(pl.col("article") == "Cat").sort("date")
    assert cat["views"].to_list() == [0, 5]  # Dec 30 missing -> 0, Dec 31 -> 5
    assert y2021.filter(pl.col("article") == "Cat").sort("date")["views"].to_list() == [9, 0]
    assert y2020["date"].dtype == pl.Date
    assert y2020["date"].min() == date(2020, 12, 30)


def test_build_parquet_rejects_out_of_range_day(tmp_path: Path) -> None:
    jsonl = tmp_path / "v.jsonl"
    jsonl.write_text('{"article":"A","views":{"2030-01-01":1}}\n', encoding="utf-8")
    with pytest.raises(FetchError, match="outside"):
        d1.build_parquet(jsonl, tmp_path / "o", date(2020, 1, 1), date(2020, 1, 5))


def test_cli_list_then_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    articles = tmp_path / "interim" / "D1" / "articles.csv"
    d1.write_article_list(articles, [d1.ArticleRow("Cat", 5, 1)])
    assert d1.main(["status", "--data-dir", str(tmp_path)]) == 0
    assert "articles listed: 1; articles downloaded: 0" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        d1.main(["list", "--data-dir", str(tmp_path)])  # no contact given
