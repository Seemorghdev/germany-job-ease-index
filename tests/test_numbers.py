from __future__ import annotations

import pytest

from jobease.sources.numbers import parse_code, parse_count, parse_decimal


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (4180, 4180),
        (4180.0, 4180),
        ("4180", 4180),
        ("4.180", 4180),
        ("1.234.567", 1_234_567),
        (" 12 ", 12),
        (None, None),
        ("", None),
        ("*", None),
        ("-", None),
    ],
)
def test_parse_count(value: object, expected: int | None) -> None:
    assert parse_count(value) == expected


@pytest.mark.parametrize("value", ["12.5", "10,4", "abc", 4.5, -3, True])
def test_parse_count_rejects_non_counts(value: object) -> None:
    with pytest.raises(ValueError):
        parse_count(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("891,12", 891.12), ("1.234,5", 1234.5), (310.7, 310.7), ("310.7", 310.7), (None, None)],
)
def test_parse_decimal(value: object, expected: float | None) -> None:
    assert parse_decimal(value) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [(5, 2, "05"), ("05", 2, "05"), (9.0, 2, "09"), (0, 3, "000"), ("", 2, None), ("x", 2, None)],
)
def test_parse_code(value: object, width: int, expected: str | None) -> None:
    assert parse_code(value, width) == expected


def test_parse_code_rejects_too_wide() -> None:
    with pytest.raises(ValueError):
        parse_code("123", 2)
