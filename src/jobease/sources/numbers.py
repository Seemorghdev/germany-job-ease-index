"""Strict parsing of numbers as they appear in German statistical spreadsheets."""

from __future__ import annotations

import re

# "1.234.567": dots as German thousands separators. "12.5" is not a count.
_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")

# Symbols the BA and Destatis use for suppressed or unavailable values.
SUPPRESSED_SYMBOLS = frozenset({"*", "-", "\u2013", "x", "X", ".", "\u2026"})


def parse_count(value: object) -> int | None:
    """Parse a non-negative whole count.

    Returns ``None`` for empty cells and suppressed values. Raises ``ValueError`` for
    anything else that isn't a whole number, so a shifted column fails loudly instead
    of producing plausible-looking numbers.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"expected a count, got boolean {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"expected a whole count, got {value!r}")
        number = int(value)
    else:
        text = str(value).strip()
        if not text or text in SUPPRESSED_SYMBOLS:
            return None
        compact = text.replace(" ", "").replace("\u00a0", "")
        if compact.isdigit():
            number = int(compact)
        elif _THOUSANDS.fullmatch(compact):
            number = int(compact.replace(".", ""))
        else:
            raise ValueError(f"expected a count, got {value!r}")
    if number < 0:
        raise ValueError(f"expected a non-negative count, got {number}")
    return number


def parse_decimal(value: object) -> float | None:
    """Parse a decimal that may use a German comma: ``"891,12"`` -> ``891.12``."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got boolean {value!r}")
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in SUPPRESSED_SYMBOLS:
        return None
    return float(text.replace(".", "").replace(",", ".")) if "," in text else float(text)


def parse_code(value: object, width: int) -> str | None:
    """Normalise a numeric code to a zero-padded string: ``5`` -> ``"05"``."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"expected a code, got boolean {value!r}")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"expected a whole-number code, got {value!r}")
        text = str(int(value))
    else:
        text = str(value).strip()
        if not text:
            return None
    if not text.isdigit():
        return None
    if len(text) > width:
        raise ValueError(f"code {text!r} is wider than {width} digits")
    return text.zfill(width)
