"""Tests for the shared download core: the polite HTTP client and manifests."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from sat.ingest.http import FetchError, Http, make_user_agent
from sat.ingest.manifest import read_manifest, record, sha256_file


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "err", headers, io.BytesIO(b""))


class Script:
    """An opener that plays back a list of results (bytes or exceptions)."""

    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.urls.append(request.full_url)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


def make_http(results: list[Any], **kwargs: Any) -> tuple[Http, Script, list[float]]:
    script = Script(results)
    sleeps: list[float] = []
    clock_value = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock_value[0] += seconds

    http = Http(
        "test-agent",
        opener=script,
        sleep=sleep,
        clock=lambda: clock_value[0],
        **kwargs,
    )
    return http, script, sleeps


def test_user_agent_requires_contact() -> None:
    assert "me@example.com" in make_user_agent("me@example.com")
    with pytest.raises(ValueError):
        make_user_agent("nobody")


def test_get_json_success() -> None:
    http, script, _ = make_http([b'{"a": 1}'], min_interval=0)
    assert http.get_json("http://x/1") == {"a": 1}
    assert script.urls == ["http://x/1"]


def test_404_is_none_not_an_error() -> None:
    http, _, _ = make_http([http_error(404)], min_interval=0)
    assert http.get_json("http://x") is None


def test_retries_temporary_errors_then_succeeds() -> None:
    http, script, sleeps = make_http([http_error(503), http_error(502), b"ok"], min_interval=0)
    assert http.get_bytes("http://x") == b"ok"
    assert len(script.urls) == 3
    assert sleeps == [1.0, 2.0]  # waits grow: 2**0, 2**1


def test_honours_retry_after() -> None:
    http, _, sleeps = make_http([http_error(429, "7"), b"ok"], min_interval=0)
    assert http.get_bytes("http://x") == b"ok"
    assert sleeps == [7.0]


def test_network_errors_are_retried() -> None:
    http, _, _ = make_http([urllib.error.URLError("down"), TimeoutError(), b"ok"], min_interval=0)
    assert http.get_bytes("http://x") == b"ok"


def test_permanent_errors_are_not_retried() -> None:
    http, script, _ = make_http([http_error(403)], min_interval=0)
    with pytest.raises(FetchError, match="403"):
        http.get_bytes("http://x")
    assert len(script.urls) == 1


def test_gives_up_after_retries() -> None:
    http, script, _ = make_http([http_error(500)] * 3, min_interval=0, retries=2)
    with pytest.raises(FetchError, match="gave up"):
        http.get_bytes("http://x")
    assert len(script.urls) == 3


def test_bad_json_is_an_error() -> None:
    http, _, _ = make_http([b"<html>"], min_interval=0)
    with pytest.raises(FetchError, match="JSON"):
        http.get_json("http://x")


def test_requests_are_spaced_by_min_interval() -> None:
    http, _, sleeps = make_http([b"1", b"2", b"3"], min_interval=0.5)
    for i in range(3):
        http.get_bytes(f"http://x/{i}")
    assert sleeps == [0.5, 0.5]  # first goes at once, then half a second apart
    assert http.request_count == 3


def test_invalid_settings_rejected() -> None:
    with pytest.raises(ValueError):
        Http("ua", retries=-1)


def test_sha256_known_value(tmp_path: Path) -> None:
    f = tmp_path / "abc.txt"
    f.write_bytes(b"abc")
    assert sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_manifest_records_and_replaces(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"abc")
    manifest = tmp_path / "m" / "D9.csv"
    when = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
    entry = record(manifest, "D9", "http://x/data", f, now=when)
    assert entry.bytes == 3 and entry.downloaded_utc == "2026-10-29T12:00:00Z"
    f.write_bytes(b"abcd")
    record(manifest, "D9", "http://x/data", f, now=when)
    record(manifest, "D9", "http://x/other", f, now=when)
    rows = read_manifest(manifest)
    assert [r.url for r in rows] == ["http://x/data", "http://x/other"]
    assert rows[0].bytes == 4  # the old row was replaced, not duplicated
    assert manifest.read_text(encoding="utf-8").startswith("dataset,url,sha256,bytes")
