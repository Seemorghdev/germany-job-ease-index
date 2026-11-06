"""A polite HTTP client: a minimum gap between requests, and retries with backoff when the
server throttles (429) or fails (5xx). Shared by every source that downloads."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Self

import httpx

USER_AGENT = "germany-job-ease-index (+https://github.com/Seemorghdev/germany-job-ease-index)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    """The server refused or failed a request, after any retries."""


class PoliteClient:
    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        min_interval_s: float = 1.0,
        max_retries: int = 5,
        max_backoff_s: float = 60.0,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._max_backoff_s = max_backoff_s
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            timeout=timeout_s,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _throttle(self) -> None:
        if self._last_request is None:
            return
        wait = self._min_interval_s - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        # Back off in multiples of the request interval: a server that wants one request a
        # minute won't forgive a retry after two seconds.
        delay = max(1.0, self._min_interval_s) * 2.0**attempt
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        self._sleep(min(self._max_backoff_s, delay))

    def get(self, url: str, params: Mapping[str, str | int] | None = None) -> httpx.Response:
        """GET ``url`` and return the 200 response; raise ``HttpError`` otherwise."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as exc:
                self._last_request = self._clock()
                last_error = exc
                if attempt < self._max_retries:
                    self._backoff(attempt, None)
                continue
            self._last_request = self._clock()
            if response.status_code in RETRY_STATUS and attempt < self._max_retries:
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code != 200:
                raise HttpError(f"HTTP {response.status_code}: {response.text[:200]}")
            return response
        raise HttpError(f"gave up after {self._max_retries + 1} attempts") from last_error
