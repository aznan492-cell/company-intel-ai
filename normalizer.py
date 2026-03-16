"""
normalizer.py — Convert raw display_value strings into typed normalized_value.

Supported types  (from FIELD_SCHEMA):
  currency    "$394.3 billion"  →  394_300_000_000.0
  percentage  "12.1%"           →  12.1
  rating_5    "4.1/5.0"         →  4.1
  integer     "742,000 employees" → 742_000
  year        "Founded 2009"    →  2009
  boolean     "Yes" / "true"    →  True / False
  string/text                   →  unchanged str (or None if blank)
"""

import re
from field_schema import FIELD_SCHEMA


# ── Multiplier table ──────────────────────────────────────────────────────────
_MULTIPLIERS = {
    "trillion": 1_000_000_000_000,
    "billion":  1_000_000_000,
    "million":  1_000_000,
    "thousand": 1_000,
    "t":        1_000_000_000_000,
    "b":        1_000_000_000,
    "m":        1_000_000,
    "k":        1_000,
}

_BOOL_TRUE  = {"yes", "true", "1", "y", "on"}
_BOOL_FALSE = {"no", "false", "0", "n", "off"}


def _parse_numeric(raw: str) -> float | None:
    """
    Extract the first numeric value from a string, applying magnitude
    suffixes (K, M, B, T, thousand, million, billion, trillion).

    Returns float or None if parsing fails.
    """
    if raw is None:
        return None

    raw = str(raw).strip()
    # Remove currency symbols and commas
    cleaned = re.sub(r"[$€£¥₹,]", "", raw)

    # Try to find a number (possibly with decimal) followed by an optional suffix
    pattern = re.compile(
        r"(-?\d+(?:\.\d+)?)\s*"
        r"(trillion|billion|million|thousand|[tTbBmMkK])?\b",
        re.IGNORECASE,
    )
    match = pattern.search(cleaned)
    if not match:
        return None

    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = _MULTIPLIERS.get(suffix, 1)
    return number * multiplier


def normalize_currency(raw) -> float | None:
    if raw is None:
        return None
    result = _parse_numeric(str(raw))
    if result is None or result < 0:
        return None
    return result


def normalize_percentage(raw) -> float | None:
    if raw is None:
        return None
    cleaned = re.sub(r"[%,\s]", "", str(raw))
    # Grab the first number
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    value = float(match.group())
    if 0.0 <= value <= 100.0:
        return value
    return None


def normalize_rating_5(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw)
    # Handle "4.1/5.0" or "4.1 out of 5" — take numerator
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:/|out of)", s, re.IGNORECASE)
    if match:
        value = float(match.group(1))
    else:
        match = re.search(r"-?\d+(?:\.\d+)?", s)
        if not match:
            return None
        value = float(match.group())
    if 0.0 <= value <= 5.0:
        return value
    return None


def normalize_integer(raw) -> int | None:
    if raw is None:
        return None
    result = _parse_numeric(str(raw))
    if result is None or result < 0:
        return None
    return int(round(result))


def normalize_year(raw) -> int | None:
    if raw is None:
        return None
    # Find a 4-digit year in range
    match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", str(raw))
    if not match:
        return None
    return int(match.group(1))


def normalize_boolean(raw) -> bool | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    return None


def normalize_text(raw) -> str | None:
    """String/text types: return stripped string or None if blank."""
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


# ── Dispatch map ─────────────────────────────────────────────────────────────
_NORMALIZERS = {
    "currency":   normalize_currency,
    "percentage": normalize_percentage,
    "rating_5":   normalize_rating_5,
    "integer":    normalize_integer,
    "year":       normalize_year,
    "boolean":    normalize_boolean,
    "string":     normalize_text,
    "text":       normalize_text,
}


def normalize_field(field_name: str, display_value) -> float | int | str | bool | None:
    """
    Normalize display_value for field_name based on its FIELD_SCHEMA type.

    Returns:
        Typed normalized value, or None if parsing fails or display_value is null.
    """
    if display_value is None:
        return None
    
    # Treat LLM-returned "null" strings as actual null
    if isinstance(display_value, str) and display_value.strip().lower() in ("null", "none", "n/a", "na", ""):
        return None

    field_type = FIELD_SCHEMA.get(field_name, {}).get("type", "string")
    normalizer_fn = _NORMALIZERS.get(field_type, normalize_text)
    try:
        return normalizer_fn(display_value)
    except Exception:
        return None
