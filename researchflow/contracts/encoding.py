"""RFC 8785 JSON Canonicalization Scheme (JCS) for WP-03.

The implementation covers the JSON value types used by the ResearchFlow API:
objects with string keys, arrays, strings, finite numbers, booleans and null.
It intentionally rejects ``NaN``/``Infinity`` and non-string object keys.

Number formatting follows the ECMAScript shortest-round-trip form for the
ranges used by this project: fixed notation for ``1e-6 <= |n| < 1e21`` and
exponent notation otherwise.  This is the same rule RFC 8785 inherits from
ECMAScript's ``Number::toString``.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

__all__ = ["canonical_bytes", "canonical_text", "hash_payload"]


def _utf16_key(value: str) -> bytes:
    """Sort keys by UTF-16 code units (RFC 8785 §3.2.3)."""

    return value.encode("utf-16-be")


def _canonical_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):  # bool is an int subclass; handled by caller
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("NaN and Infinity are not valid JCS numbers")
    if value == 0:
        return "0"
    if 1e-6 <= abs(value) < 1e21:
        text = format(Decimal(repr(value)), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in {"-0", ""} else text
    text = repr(value).lower()
    if "e" not in text:
        # Extremely defensive: normalise a fixed representation into exponent
        # form.  ``repr`` normally uses exponent form outside the fixed range.
        text = format(Decimal(text), "e")
    mantissa, exponent = text.split("e", 1)
    exponent_int = int(exponent)
    sign = "+" if exponent_int >= 0 else "-"
    return f"{mantissa}e{sign}{abs(exponent_int)}"


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return _canonical_number(value)
    if isinstance(value, float):
        return _canonical_number(value)
    if isinstance(value, str):
        return _canonical_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JCS object keys must be strings")
        keys = sorted(value.keys(), key=_utf16_key)
        return (
            "{"
            + ",".join(
                _canonical_string(key) + ":" + _canonical(value[key]) for key in keys
            )
            + "}"
        )
    raise TypeError(f"unsupported JCS value type: {type(value).__name__}")


def canonical_text(value: Any) -> str:
    """Return the RFC 8785 canonical JSON text for ``value``."""

    return _canonical(value)


def canonical_bytes(value: Any) -> bytes:
    """Return the RFC 8785 canonical JSON as UTF-8 bytes."""

    return canonical_text(value).encode("utf-8")


def hash_payload(value: Any) -> str:
    """Return the lowercase SHA-256 hex digest of canonical UTF-8 bytes."""

    return hashlib.sha256(canonical_bytes(value)).hexdigest()