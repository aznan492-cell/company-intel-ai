"""
confidence.py — Calculate per-field confidence scores.

Base score by source:
  majority       → 0.95  (2+ models agreed)
  llm_judge      → 0.85  (Gemini arbitrated)
  longest        → 0.70  (heuristic pick)
  gemini/groq/openrouter → 0.65 (only one model had a value)
  missing/none   → 0.0   (field was absent from all models)

Adjustments:
  - normalized_value is None → 0.0
  - subtract 0.05 per retry attempt (floor = 0.0)
"""

_SOURCE_BASE: dict[str, float] = {
    # Original Agent 2 sources
    "majority":          0.95,
    "llm_judge":         0.85,
    "longest":           0.70,
    "gemini":            0.65,
    "groq":              0.65,
    "openrouter":        0.65,
    "missing":           0.0,
    "none":              0.0,
    "unknown":           0.0,
    # Retry sources (prefixed with retry_)
    "retry_majority":    0.90,   # slightly lower than original — one retry cycle
    "retry_llm_judge":   0.80,
    "retry_longest":     0.65,
    "retry_gemini":      0.60,
    "retry_groq":        0.60,
    "retry_openrouter":  0.60,
    "unresolved":        0.0,
}

_RETRY_PENALTY = 0.05


def calculate_confidence(
    source: str,
    normalized_value,
    retry_count: int = 0,
) -> float:
    """
    Compute a 0.0–1.0 confidence score for a single field.

    Args:
        source:           Source label from Agent 2 (e.g. "majority", "groq").
        normalized_value: The parsed typed value (None = parse failed).
        retry_count:      Number of retry attempts already made for this field.

    Returns:
        float in [0.0, 1.0]
    """
    # Always zero when normalized_value couldn't be computed
    if normalized_value is None:
        return 0.0

    base = _SOURCE_BASE.get(source, 0.65)
    penalty = retry_count * _RETRY_PENALTY
    return max(0.0, round(base - penalty, 4))
