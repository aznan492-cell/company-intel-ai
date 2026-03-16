"""
runtime_validator.py — Per-field and whole-company validation engine.

Uses FIELD_SCHEMA as the single source of truth for types and nullability.

Cross-field rules:
  - annual_profit (normalized) must not exceed annual_revenue (normalized)
  - incorporation_year (normalized) must be <= current year (2026)
  - employee_size (normalized) must be >= 0

Returns:
  {"status": "pass" | "fail", "errors": [{"field": "...", "reason": "..."}]}
"""

import datetime
from field_schema import FIELD_SCHEMA

_CURRENT_YEAR = datetime.datetime.now().year


# ── Required envelope keys ────────────────────────────────────────────────────
_REQUIRED_KEYS = {"display_value", "normalized_value", "source", "confidence"}


def _check_type(field_name: str, normalized_value) -> str | None:
    """
    Validate that normalized_value conforms to the schema type.
    Returns an error reason string, or None if valid.
    """
    if normalized_value is None:
        return None  # Type check skipped for None (nullability is checked separately)

    field_type = FIELD_SCHEMA.get(field_name, {}).get("type", "string")

    if field_type == "currency":
        if not isinstance(normalized_value, (int, float)) or normalized_value < 0:
            return f"currency must be a non-negative number (got {normalized_value!r})"

    elif field_type == "percentage":
        if not isinstance(normalized_value, (int, float)) or not (0.0 <= normalized_value <= 100.0):
            return f"percentage must be between 0 and 100 (got {normalized_value!r})"

    elif field_type == "year":
        if not isinstance(normalized_value, int) or not (1800 <= normalized_value <= _CURRENT_YEAR):
            return f"year must be between 1800 and {_CURRENT_YEAR} (got {normalized_value!r})"

    elif field_type == "integer":
        if not isinstance(normalized_value, (int, float)) or normalized_value < 0:
            return f"integer must be >= 0 (got {normalized_value!r})"

    elif field_type == "rating_5":
        if not isinstance(normalized_value, (int, float)) or not (0.0 <= normalized_value <= 5.0):
            return f"rating_5 must be between 0 and 5 (got {normalized_value!r})"

    elif field_type in ("string", "text"):
        if not isinstance(normalized_value, str) or not normalized_value.strip():
            return f"string/text must be a non-empty string (got {normalized_value!r})"

    elif field_type == "boolean":
        if not isinstance(normalized_value, bool):
            return f"boolean must be True or False (got {normalized_value!r})"

    return None


def validate_field(field_name: str, field_data: dict) -> list[dict]:
    """
    Validate a single field envelope.

    Args:
        field_name: Name of the field (must be in FIELD_SCHEMA).
        field_data: The full envelope dict for this field.

    Returns:
        List of {"field": ..., "reason": ...} error dicts (empty = valid).
    """
    errors: list[dict] = []

    # 1. Field must be in FIELD_SCHEMA
    if field_name not in FIELD_SCHEMA:
        errors.append({"field": field_name, "reason": "field not in FIELD_SCHEMA"})
        return errors

    # 2. Envelope must be a dict with required keys
    if not isinstance(field_data, dict):
        errors.append({"field": field_name, "reason": "field_data must be a dict"})
        return errors

    missing_keys = _REQUIRED_KEYS - set(field_data.keys())
    if missing_keys:
        errors.append({
            "field": field_name,
            "reason": f"envelope missing keys: {sorted(missing_keys)}",
        })
        return errors

    normalized_value = field_data.get("normalized_value")
    schema = FIELD_SCHEMA[field_name]

    # 3. Non-nullable check
    if not schema["nullable"] and normalized_value is None:
        errors.append({
            "field": field_name,
            "reason": f"non-nullable field has null normalized_value",
        })

    # 4. Type validation (only if non-None)
    if normalized_value is not None:
        type_error = _check_type(field_name, normalized_value)
        if type_error:
            errors.append({"field": field_name, "reason": type_error})

    return errors


def validate_company(data: dict) -> dict:
    """
    Validate a full company data dict (all 163 fields).

    Args:
        data: {field_name: envelope_dict, ...}

    Returns:
        {"status": "pass" | "fail", "errors": [...]}
    """
    errors: list[dict] = []

    import os
    if os.getenv("TEST_MINI") == "1":
        from schema import MiniCompanyOverview
        target_fields = list(MiniCompanyOverview.model_fields.keys())
    else:
        target_fields = FIELD_SCHEMA.keys()

    # 1. All target keys must exist
    for field_name in target_fields:
        if field_name not in data:
            errors.append({"field": field_name, "reason": "field missing from data"})
            continue

        field_errors = validate_field(field_name, data[field_name])
        errors.extend(field_errors)

    # 2. Cross-field rules (only when both fields exist with numeric values)
    annual_revenue_norm    = _get_normalized(data, "annual_revenue")
    annual_profit_norm     = _get_normalized(data, "annual_profit")
    incorporation_year_norm = _get_normalized(data, "incorporation_year")
    employee_size_norm     = _get_normalized(data, "employee_size")

    if (annual_revenue_norm is not None
            and annual_profit_norm is not None
            and isinstance(annual_revenue_norm, (int, float))
            and isinstance(annual_profit_norm, (int, float))
            and annual_profit_norm > annual_revenue_norm):
        errors.append({
            "field": "annual_profit",
            "reason": (
                f"annual_profit ({annual_profit_norm}) cannot exceed "
                f"annual_revenue ({annual_revenue_norm})"
            ),
        })

    if (incorporation_year_norm is not None
            and isinstance(incorporation_year_norm, int)
            and incorporation_year_norm > _CURRENT_YEAR):
        errors.append({
            "field": "incorporation_year",
            "reason": f"incorporation_year ({incorporation_year_norm}) exceeds current year ({_CURRENT_YEAR})",
        })

    if (employee_size_norm is not None
            and isinstance(employee_size_norm, (int, float))
            and employee_size_norm < 0):
        errors.append({
            "field": "employee_size",
            "reason": f"employee_size ({employee_size_norm}) must be >= 0",
        })

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }


def _get_normalized(data: dict, field_name: str):
    """Safely extract normalized_value from a field envelope."""
    entry = data.get(field_name)
    if isinstance(entry, dict):
        return entry.get("normalized_value")
    return None
