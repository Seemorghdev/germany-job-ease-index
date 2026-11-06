"""BA job board (Jobsuche) search endpoint: listing counts and listing pages.

The endpoint and key are the ones the BA web app uses, documented by the community
project https://github.com/bundesAPI/jobsuche-api. Field names follow the v6 responses
(see bundesAPI/jobsuche-api#69). Full responses are kept in the raw store, and listings
stay in the local warehouse: neither is ever published.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, Self

import httpx

from jobease.http import HttpError, PoliteClient


class JobsucheError(HttpError):
    """The job board refused or failed a request."""


class JobsucheSchemaError(JobsucheError):
    """The response doesn't have the shape we rely on (see bundesAPI/jobsuche-api#69)."""


@dataclass(frozen=True)
class SearchQuery:
    term: str
    where: str
    radius_km: int
    window_days: int | None  # None: every open listing, however old

    def params(self, *, page: int = 1, size: int = 1) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "was": self.term,
            "wo": self.where,
            "umkreis": self.radius_km,
            "angebotsart": 1,  # 1 = employment (not training or self-employment)
            "size": size,
            "page": page,
        }
        if self.window_days is not None:
            params["veroeffentlichtseit"] = self.window_days
        return params


@dataclass(frozen=True)
class CountResult:
    query: SearchQuery
    total: int
    body: bytes
    fetched_at: datetime


@dataclass(frozen=True)
class Listing:
    reference: str
    title: str | None
    employer: str | None
    employer_hash: str | None
    occupation: str | None
    published_on: date | None
    changed_at: datetime | None
    postcode: str | None
    place: str | None
    full_time: bool | None
    part_time: bool | None
    marginal: bool | None  # Minijob (geringfügige Beschäftigung)
    lateral_entry: bool | None  # open to career changers (Quereinstieg)
    contract_duration: str | None
    pay_info: str | None


@dataclass(frozen=True)
class PageResult:
    query: SearchQuery
    page: int
    total: int
    listings: tuple[Listing, ...]
    facets: Mapping[str, Any]
    body: bytes
    fetched_at: datetime


def _payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise JobsucheSchemaError(f"response is not JSON: {body[:120]!r}") from exc
    if not isinstance(payload, dict):
        raise JobsucheSchemaError(f"expected a JSON object, got {type(payload).__name__}")
    return payload


def _total(payload: Mapping[str, Any]) -> int:
    total = payload.get("maxErgebnisse")
    if isinstance(total, bool) or total is None:
        raise JobsucheSchemaError(f"no 'maxErgebnisse' in response; keys: {sorted(payload)[:20]}")
    if isinstance(total, str) and total.isdigit():
        return int(total)
    if isinstance(total, int) and total >= 0:
        return total
    raise JobsucheSchemaError(f"'maxErgebnisse' is not a count: {total!r}")


def parse_total(body: bytes) -> int:
    return _total(_payload(body))


def _text(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise JobsucheSchemaError(f"'{key}' is not text: {value!r}")
    return value.strip() or None


def _flag(item: Mapping[str, Any], key: str) -> bool | None:
    value = item.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise JobsucheSchemaError(f"'{key}' is not true/false: {value!r}")


def _date(value: str | None, key: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError as exc:
        raise JobsucheSchemaError(f"'{key}' is not a date: {value!r}") from exc


def _datetime(value: str | None, key: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError as exc:
        raise JobsucheSchemaError(f"'{key}' is not a timestamp: {value!r}") from exc


def _first_address(item: Mapping[str, Any]) -> Mapping[str, Any]:
    locations = item.get("stellenlokationen")
    if not isinstance(locations, list) or not locations or not isinstance(locations[0], dict):
        return {}
    address = locations[0].get("adresse")
    return address if isinstance(address, dict) else {}


def parse_listing(item: object) -> Listing:
    if not isinstance(item, dict):
        raise JobsucheSchemaError(f"listing is not an object: {item!r:.80}")
    reference = _text(item, "referenznummer")
    if reference is None:
        raise JobsucheSchemaError(f"listing without 'referenznummer'; keys: {sorted(item)[:20]}")
    address = _first_address(item)
    part_shifts = [
        _flag(item, "arbeitszeitTeilzeitVormittag"),
        _flag(item, "arbeitszeitTeilzeitNachmittag"),
    ]
    published = "datumErsteVeroeffentlichung"
    return Listing(
        reference=reference,
        title=_text(item, "stellenangebotsTitel"),
        employer=_text(item, "firma"),
        employer_hash=_text(item, "arbeitgeberKundennummerHash"),
        occupation=_text(item, "hauptberuf"),
        published_on=_date(_text(item, published), published),
        changed_at=_datetime(_text(item, "aenderungsdatum"), "aenderungsdatum"),
        postcode=_text(address, "plz"),
        place=_text(address, "ort"),
        full_time=_flag(item, "arbeitszeitVollzeit"),
        part_time=None if part_shifts == [None, None] else any(part_shifts),
        marginal=_flag(item, "istGeringfuegigeBeschaeftigung"),
        lateral_entry=_flag(item, "quereinstiegGeeignet"),
        contract_duration=_text(item, "vertragsdauer"),
        pay_info=_text(item, "verguetungsangabe"),
    )


def parse_page(body: bytes) -> tuple[int, tuple[Listing, ...], Mapping[str, Any]]:
    """Total, listings and facets of one result page."""
    payload = _payload(body)
    total = _total(payload)
    items = payload.get("ergebnisliste")
    if items is None:
        items = []  # the board omits the list on an empty page
    if not isinstance(items, list):
        raise JobsucheSchemaError(f"'ergebnisliste' is not a list: {type(items).__name__}")
    facets = payload.get("facetten") or {}
    if not isinstance(facets, dict):
        raise JobsucheSchemaError(f"'facetten' is not an object: {type(facets).__name__}")
    return total, tuple(parse_listing(i) for i in items), facets


class JobsucheClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        min_interval_s: float = 1.0,
        max_retries: int = 5,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url
        self._http = PoliteClient(
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            min_interval_s=min_interval_s,
            max_retries=max_retries,
            timeout_s=timeout_s,
            transport=transport,
            sleep=sleep,
            clock=clock,
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

    def _get(self, query: SearchQuery, *, page: int, size: int) -> httpx.Response:
        try:
            return self._http.get(self._base_url, params=query.params(page=page, size=size))
        except HttpError as exc:
            raise JobsucheError(f"{exc} for {query}, page {page}") from exc

    def count(self, query: SearchQuery) -> CountResult:
        response = self._get(query, page=1, size=1)
        return CountResult(
            query=query,
            total=parse_total(response.content),
            body=response.content,
            fetched_at=datetime.now(UTC),
        )

    def page(self, query: SearchQuery, *, page: int, size: int) -> PageResult:
        response = self._get(query, page=page, size=size)
        total, listings, facets = parse_page(response.content)
        return PageResult(
            query=query,
            page=page,
            total=total,
            listings=listings,
            facets=facets,
            body=response.content,
            fetched_at=datetime.now(UTC),
        )
