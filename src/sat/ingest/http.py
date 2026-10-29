"""A small, polite HTTP client.

Why it exists: every data source has limits, and our connection is slow. This client
  * spaces requests out (one shared clock, safe to use from several threads),
  * retries temporary failures with growing waits and honours ``Retry-After``,
  * treats "404 not found" as a normal answer (``None``), not a crash,
  * announces who we are in the User-Agent, as Wikimedia and npm ask.

Network access, the clock and sleeping are all injectable, so tests never touch the internet.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Opener = Callable[[urllib.request.Request, float], Any]


class FetchError(RuntimeError):
    """A request failed for good (not merely temporarily)."""


def default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def make_user_agent(contact: str) -> str:
    """The identification string sent with every request."""
    if "@" not in contact and "://" not in contact:
        raise ValueError("contact must be an email address or a URL")
    return f"seasonal-tiering-poc/0.1 (research; contact: {contact})"


class Http:
    """Rate-limited GET requests with retries."""

    def __init__(
        self,
        user_agent: str,
        *,
        min_interval: float = 0.2,
        retries: int = 5,
        timeout: float = 60.0,
        opener: Opener | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_interval < 0 or retries < 0 or timeout <= 0:
            raise ValueError("min_interval and retries must be >= 0 and timeout > 0")
        self.user_agent = user_agent
        self._min_interval = min_interval
        self._retries = retries
        self._timeout = timeout
        self._opener = opener or default_opener
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self.request_count = 0

    def _wait_for_turn(self) -> None:
        """Reserve the next time slot; sleep until it arrives."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._min_interval
            self.request_count += 1
        delay = slot - now
        if delay > 0:
            self._sleep(delay)

    @staticmethod
    def _retry_after(error: urllib.error.HTTPError) -> float | None:
        value = error.headers.get("Retry-After") if error.headers else None
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def get_bytes(self, url: str) -> bytes | None:
        """Return the response body, or ``None`` if the server says 404."""
        last_problem = "no attempt made"
        for attempt in range(self._retries + 1):
            self._wait_for_turn()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})  # noqa: S310
            try:
                with self._opener(request, self._timeout) as response:
                    body: bytes = response.read()
                    return body
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if error.code not in RETRYABLE_STATUS:
                    raise FetchError(f"HTTP {error.code} for {url}") from error
                last_problem = f"HTTP {error.code}"
                wait = self._retry_after(error)
                backoff = wait if wait is not None else min(2.0**attempt, 60.0)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                last_problem = f"{type(error).__name__}: {error}"
                backoff = min(2.0**attempt, 60.0)
            if attempt < self._retries:
                self._sleep(backoff)
        raise FetchError(f"gave up on {url} after {self._retries + 1} attempts ({last_problem})")

    def get_json(self, url: str) -> Any | None:
        """Return parsed JSON, or ``None`` on 404. Bad JSON is an error."""
        body = self.get_bytes(url)
        if body is None:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FetchError(f"response from {url} was not valid JSON") from error
