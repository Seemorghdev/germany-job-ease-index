from __future__ import annotations

import json

import httpx
import pytest

from jobease.sources.jobsuche import (
    JobsucheClient,
    JobsucheError,
    JobsucheSchemaError,
    SearchQuery,
    parse_total,
)

QUERY = SearchQuery(term="Lagerhelfer", where="Münster", radius_km=0, window_days=30)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler: httpx.MockTransport, clock: FakeClock, **kwargs: float) -> JobsucheClient:
    return JobsucheClient(
        base_url="https://example.test/jobs",
        api_key="test-key",
        transport=handler,
        sleep=clock.sleep,
        clock=clock,
        **kwargs,  # type: ignore[arg-type]
    )


def _ok(total: int) -> httpx.Response:
    return httpx.Response(200, json={"maxErgebnisse": total, "stellenangebote": []})


def test_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(42)

    with _client(httpx.MockTransport(handler), FakeClock()) as client:
        result = client.count(QUERY)

    assert result.total == 42
    request = seen[0]
    assert request.headers["X-API-Key"] == "test-key"
    assert dict(request.url.params) == {
        "was": "Lagerhelfer",
        "wo": "Münster",
        "umkreis": "0",
        "veroeffentlichtseit": "30",
        "angebotsart": "1",
        "size": "1",
        "page": "1",
    }


def test_retries_transient_errors_then_succeeds() -> None:
    responses = iter(
        [httpx.Response(503), httpx.Response(429, headers={"Retry-After": "3"}), _ok(7)]
    )
    clock = FakeClock()
    with _client(httpx.MockTransport(lambda _: next(responses)), clock) as client:
        assert client.count(QUERY).total == 7
    assert 3.0 in clock.sleeps  # honoured Retry-After


def test_forbidden_is_not_retried() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, text="forbidden")

    with (
        _client(httpx.MockTransport(handler), FakeClock()) as client,
        pytest.raises(JobsucheError, match="403"),
    ):
        client.count(QUERY)
    assert calls == 1


def test_gives_up_after_max_retries() -> None:
    with (
        _client(
            httpx.MockTransport(lambda _: httpx.Response(503)), FakeClock(), max_retries=2
        ) as client,
        pytest.raises(JobsucheError, match="503"),
    ):
        client.count(QUERY)


def test_throttles_between_requests() -> None:
    clock = FakeClock()
    with _client(httpx.MockTransport(lambda _: _ok(1)), clock, min_interval_s=1.0) as client:
        client.count(QUERY)
        client.count(QUERY)
    assert clock.sleeps == [pytest.approx(1.0)]


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        json.dumps({"total": 3}).encode(),
        json.dumps({"maxErgebnisse": -1}).encode(),
    ],
)
def test_unexpected_response_shape_is_a_schema_error(body: bytes) -> None:
    with pytest.raises(JobsucheSchemaError):
        parse_total(body)


def test_total_as_numeric_string_is_accepted() -> None:
    assert parse_total(json.dumps({"maxErgebnisse": "12"}).encode()) == 12
