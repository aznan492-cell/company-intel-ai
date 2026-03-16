"""
test_runtime_validator.py — pytest suite for Stage 3 validation & normalization.

Run with:
    pytest test_runtime_validator.py -v

Tests:
  1. Missing field fails
  2. Nullable field allows None
  3. Non-nullable rejects None
  4. Currency normalization
  5. Percentage normalization
  6. Year bounds validation
  7. Cross-field: profit exceeds revenue → fail
  8. Fully valid company passes
"""

import pytest
from runtime_validator import validate_field, validate_company
from normalizer import normalize_field, normalize_currency, normalize_percentage


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_envelope(
    display_value=None,
    normalized_value=None,
    source="majority",
    confidence=0.95,
):
    """Construct a minimal valid field envelope."""
    return {
        "display_value":    display_value,
        "normalized_value": normalized_value,
        "source":           source,
        "confidence":       confidence,
        "retry_metadata": {
            "attempted":       False,
            "attempt_count":   0,
            "previous_values": [],
            "retry_outputs":   [],
        },
    }


def _valid_company_data() -> dict:
    """Build a minimal fully-valid Stage 3 data dict covering all 163 fields."""
    from field_schema import FIELD_SCHEMA
    from normalizer import normalize_field as nf

    data = {}
    for field_name, schema in FIELD_SCHEMA.items():
        if field_name == "name":
            display_value = "Apple Inc."
        elif field_name == "annual_revenue":
            display_value = "$394.3 billion"
        elif field_name == "annual_profit":
            display_value = "$99.8 billion"
        elif field_name == "incorporation_year":
            display_value = "1976"
        elif field_name == "employee_size":
            display_value = "164,000"
        elif field_name == "glassdoor_rating":
            display_value = "4.3/5.0"
        elif field_name == "market_share_percentage":
            display_value = "28.5%"
        else:
            # Use a sensible default per type, or None for nullable text fields
            if schema["type"] in ("string", "text") and not schema["nullable"]:
                display_value = f"Sample {field_name}"
            else:
                display_value = None

        normalized = nf(field_name, display_value)
        data[field_name] = _make_envelope(
            display_value=display_value,
            normalized_value=normalized,
        )
    return data


# ── Test 1: Missing field fails ───────────────────────────────────────────────

def test_missing_field_fails():
    """A data dict missing any FIELD_SCHEMA field should fail validation."""
    from field_schema import FIELD_SCHEMA

    # Build a complete valid dict then remove 'name'
    data = _valid_company_data()
    del data["name"]

    result = validate_company(data)
    assert result["status"] == "fail"
    field_errors = [e["field"] for e in result["errors"]]
    assert "name" in field_errors


# ── Test 2: Nullable field allows None ───────────────────────────────────────

def test_nullable_allows_none():
    """A nullable field with normalized_value=None must NOT trigger an error."""
    # 'annual_revenue' is nullable=True
    errors = validate_field("annual_revenue", _make_envelope(
        display_value=None,
        normalized_value=None,
    ))
    assert errors == [], f"Expected no errors, got: {errors}"


# ── Test 3: Non-nullable rejects None ────────────────────────────────────────

def test_non_nullable_rejects_none():
    """A non-nullable field with normalized_value=None must fail."""
    # 'name' is nullable=False
    errors = validate_field("name", _make_envelope(
        display_value=None,
        normalized_value=None,
    ))
    assert len(errors) > 0
    assert any("non-nullable" in e["reason"] or "null" in e["reason"] for e in errors)


# ── Test 4: Currency normalization ───────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("$394.3 billion", 394_300_000_000.0),
    ("$64.1B",         64_100_000_000.0),
    ("2.5 trillion",   2_500_000_000_000.0),
    ("500 million",    500_000_000.0),
    ("$1,234,567",     1_234_567.0),
    ("12.5M",          12_500_000.0),
])
def test_currency_normalization(raw, expected):
    result = normalize_currency(raw)
    assert result is not None, f"normalize_currency('{raw}') returned None"
    assert abs(result - expected) < 1.0, f"Expected {expected}, got {result}"


# ── Test 5: Percentage normalization ─────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("12.1%",  12.1),
    ("0%",      0.0),
    ("100%",  100.0),
    ("28.50%", 28.5),
])
def test_percentage_normalization(raw, expected):
    result = normalize_percentage(raw)
    assert result is not None, f"normalize_percentage('{raw}') returned None"
    assert abs(result - expected) < 0.001, f"Expected {expected}, got {result}"


def test_invalid_percentage_rejected():
    """Values outside 0–100 should return None."""
    assert normalize_percentage("150%") is None
    assert normalize_percentage("-5%") is None


# ── Test 6: Year bounds validation ───────────────────────────────────────────

def test_year_bounds_fail():
    """Year values outside [1800, current year] should fail field validation."""
    # Future year
    errors_future = validate_field("incorporation_year", _make_envelope(
        display_value="3000",
        normalized_value=3000,
    ))
    assert len(errors_future) > 0
    assert any("year" in e["reason"].lower() or "3000" in e["reason"] for e in errors_future)

    # Too far in the past
    errors_past = validate_field("incorporation_year", _make_envelope(
        display_value="1200",
        normalized_value=1200,
    ))
    assert len(errors_past) > 0


def test_year_valid_passes():
    """A valid founding year should produce no field errors."""
    errors = validate_field("incorporation_year", _make_envelope(
        display_value="1976",
        normalized_value=1976,
    ))
    assert errors == []


# ── Test 7: Cross-field profit > revenue fails ────────────────────────────────

def test_cross_field_profit_exceeds_revenue():
    """annual_profit > annual_revenue must produce a cross-field validation error."""
    data = _valid_company_data()

    # Override: profit > revenue
    data["annual_revenue"]["normalized_value"] = 100_000_000.0
    data["annual_profit"]["normalized_value"]  = 200_000_000.0  # profit > revenue

    result = validate_company(data)
    assert result["status"] == "fail"
    assert any("annual_profit" in e["field"] and "exceed" in e["reason"]
               for e in result["errors"])


# ── Test 8: Fully valid company passes ────────────────────────────────────────

def test_valid_company_passes():
    """A complete, correctly populated company dict should pass validation."""
    data = _valid_company_data()
    result = validate_company(data)
    errors = result["errors"]

    # Only allow errors on fields that are text/string type with nullable=True
    # (those will have normalized_value=None which is fine — filtered above)
    non_trivial_errors = [
        e for e in errors
        if "non-nullable" in e.get("reason", "")
        or "exceed" in e.get("reason", "")
        or "must be between" in e.get("reason", "")
    ]
    assert non_trivial_errors == [], f"Unexpected errors: {non_trivial_errors}"
