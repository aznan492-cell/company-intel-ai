"""
structure_upgrade.py — Transform Agent 2's consolidated output into the
full Stage 3 envelope format.

Input (from main.py after run_judge):
  {
    "field_name": {"value": "...", "source": "majority"},
    ...
  }

Output (one entry per FIELD_SCHEMA key — all 163 fields guaranteed):
  {
    "field_name": {
      "display_value":   "...",
      "normalized_value": <typed | None>,
      "source":          "majority",
      "confidence":      0.95,
      "retry_metadata":  {
        "attempted":       False,
        "attempt_count":   0,
        "previous_values": [],
        "retry_outputs":   []
      }
    }
  }
"""

from field_schema import FIELD_SCHEMA
from normalizer import normalize_field
from confidence import calculate_confidence


def _make_envelope(display_value, source: str, retry_count: int = 0) -> dict:
    """Build a single field envelope."""
    normalized = normalize_field.__wrapped__(display_value) if hasattr(normalize_field, "__wrapped__") else None
    return {
        "display_value":    display_value,
        "normalized_value": normalized,
        "source":           source,
        "confidence":       calculate_confidence(source, normalized, retry_count),
        "retry_metadata": {
            "attempted":       False,
            "attempt_count":   0,
            "previous_values": [],
            "retry_outputs":   [],
        },
    }


def upgrade_structure(consolidated_data: dict) -> dict:
    """
    Convert Agent 2's flat consolidated dict into full Stage 3 envelopes.

    Guarantees that ALL 163 FIELD_SCHEMA keys are present in the output,
    even if never seen from any LLM (filled with null + source="missing").

    Args:
        consolidated_data: {field: {"value": ..., "source": ...}, ...}

    Returns:
        {field: full_envelope, ...}  — all 163 fields present.
    """
    upgraded: dict = {}

    import os
    if os.getenv("TEST_MINI") == "1":
        from schema import MiniCompanyOverview
        target_fields = list(MiniCompanyOverview.model_fields.keys())
    else:
        target_fields = FIELD_SCHEMA.keys()

    for field_name in target_fields:
        if field_name in consolidated_data:
            raw_entry = consolidated_data[field_name]
            # Handle both {"value":..., "source":...} and raw scalar
            if isinstance(raw_entry, dict):
                display_value = raw_entry.get("value")
                source = raw_entry.get("source", "unknown")
            else:
                display_value = raw_entry
                source = "unknown"
        else:
            display_value = None
            source = "missing"

        # Clean up LLM "null" strings → real None
        if isinstance(display_value, str) and display_value.strip().lower() in ("null", "none", "n/a", "na", ""):
            display_value = None

        normalized = normalize_field(field_name, display_value)
        confidence = calculate_confidence(source, normalized, retry_count=0)

        upgraded[field_name] = {
            "display_value":    display_value,
            "normalized_value": normalized,
            "source":           source,
            "confidence":       confidence,
            "retry_metadata": {
                "attempted":       False,
                "attempt_count":   0,
                "previous_values": [],
                "retry_outputs":   [],
            },
        }

    return upgraded
