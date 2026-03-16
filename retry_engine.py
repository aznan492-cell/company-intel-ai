"""
retry_engine.py — Multi-model retry for fields that fail validation.

Strategy:
  1. Call all 3 LLMs in parallel with a strict single-field prompt.
  2. Apply Agent 2 merge logic:
       - 2/3 agree        → majority
       - 1 valid, rest null → take the valid one
       - All differ       → Gemini arbitration (1 extra call)
  3. Normalize and recalculate confidence.
  4. Update retry_metadata on the field envelope.

Only retries fields where:
  - nullable=False AND normalized_value is None, OR
  - type is in RETRYABLE_TYPES (currency, %, year, integer, rating_5) AND null

Max retry cycles: 2 (enforced by pipeline.py).
"""

import asyncio
import json
from typing import Any

from llm_config import get_gemini_llm, get_groq_llm, get_openrouter_llm
from rate_limiter import RateLimiter
from normalizer import normalize_field
from confidence import calculate_confidence
from field_schema import is_retryable, FIELD_SCHEMA

# ── Retry prompt template ─────────────────────────────────────────────────────
_RETRY_PROMPT = """\
You previously generated company data for: {company_name}

The following field failed validation:

Field: {field_name}
Reason: {validation_reason}

Previous values from each model:
  Gemini:      {gemini_value}
  Groq:        {groq_value}
  OpenRouter:  {openrouter_value}

Regenerate ONLY this field with the most accurate, verifiable data available.

RULES:
1. Return STRICT JSON only — no markdown, no explanation, no extra keys.
2. If numeric, return a raw number (e.g. 394300000000, not "$394.3 billion").
3. If genuinely unknown, return null.
4. Use the latest available fiscal year / calendar year data.

Expected format:
{{"{field_name}": <value>}}
"""


async def _call_single_llm(llm, prompt: str) -> Any | None:
    """Invoke one LLM and return the first value from parsed JSON, or None on failure."""
    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        # Strip markdown fences
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return next(iter(parsed.values()), None)
        return parsed
    except Exception:
        return None


def _merge_three(values: dict[str, Any | None]) -> tuple[Any | None, str]:
    """
    Mini merge: same logic as Agent 2's _pick_best_value but inline.

    Returns (best_value, source_label) where source is prefixed with 'retry_'
    to indicate the value was resolved in a retry cycle.
    Unresolved (all null) → (None, 'unresolved').
    """
    non_null = {src: v for src, v in values.items() if v is not None and str(v).strip() not in ("", "null")}

    if not non_null:
        return None, "unresolved"

    if len(non_null) == 1:
        src, val = next(iter(non_null.items()))
        return val, f"retry_{src}"  # e.g. retry_gemini

    # Check for majority (2/3 same normalized string)
    from collections import Counter
    norm = {src: str(v).strip().lower() for src, v in non_null.items()}
    counts = Counter(norm.values())
    most_common_norm, count = counts.most_common(1)[0]

    if count >= 2:
        for src, nv in norm.items():
            if nv == most_common_norm:
                return non_null[src], "retry_majority"

    # All differ → longest
    longest_src = max(non_null, key=lambda s: len(str(non_null[s])))
    return non_null[longest_src], "retry_longest"


async def _arbitrate_with_gemini(
    field_name: str,
    values: dict[str, Any],
    rate_limiter: RateLimiter,
) -> tuple[Any | None, str]:
    """Ask Gemini to pick the best of 3 differing values. Returns (value, 'retry_llm_judge')."""
    prompt = (
        f"You are a data quality judge.\n"
        f"Three models gave different values for the field '{field_name}':\n"
        f"{json.dumps(values, indent=2)}\n\n"
        f"Return ONLY a JSON object: {{\"best_value\": <the best answer>}}\n"
        f"No explanation. Strict JSON only."
    )
    try:
        await rate_limiter.wait()
        llm = get_gemini_llm()
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:])
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        return parsed.get("best_value"), "retry_llm_judge"
    except Exception:
        return None, "retry_longest"


async def retry_single_field(
    field_name: str,
    field_data: dict,
    company_name: str,
    agent1_results: dict,
    validation_reason: str,
    rate_limiter: RateLimiter,
) -> dict:
    """
    Retry one field with all 3 LLMs in parallel.

    previous_values: per-model original Agent 1 values before this retry
    retry_outputs:   per-model normalized values returned by this retry call

    Returns an updated field_data dict.
    """
    prev_display = field_data.get("display_value")
    meta = dict(field_data.get("retry_metadata", {}))

    # Capture original Agent 1 values per model (ONLY on the first attempt)
    if not meta.get("previous_values"):
        meta["previous_values"] = [
            {"model": src, "value": agent1_results.get(src, {}).get(field_name)}
            for src in ("gemini", "groq", "openrouter")
        ]

    # Build the retry prompt
    prompt = _RETRY_PROMPT.format(
        company_name=company_name,
        field_name=field_name,
        validation_reason=validation_reason,
        gemini_value=agent1_results.get("gemini", {}).get(field_name, "N/A"),
        groq_value=agent1_results.get("groq", {}).get(field_name, "N/A"),
        openrouter_value=agent1_results.get("openrouter", {}).get(field_name, "N/A"),
    )

    # Parallel call: respect rate limiter by spacing slightly
    async def _call_with_delay(llm, delay: float):
        if delay > 0:
            await asyncio.sleep(delay)
        await rate_limiter.wait()
        return await _call_single_llm(llm, prompt)

    gemini_val, groq_val, openrouter_val = await asyncio.gather(
        _call_with_delay(get_gemini_llm(), 0),
        _call_with_delay(get_groq_llm(), 1.0),
        _call_with_delay(get_openrouter_llm(), 2.0),
    )

    raw_values = {
        "gemini":     gemini_val,
        "groq":       groq_val,
        "openrouter": openrouter_val,
    }

    # Build per-model normalized retry_outputs
    retry_outputs_entry = [
        {"model": src, "value": normalize_field(field_name, val)}
        for src, val in raw_values.items()
    ]

    # Merge
    best_value, source_label = _merge_three(raw_values)

    # Arbitrate if all differ (retry_longest with 3 non-null → one more Gemini call)
    non_null_count = sum(1 for v in raw_values.values() if v is not None)
    if source_label == "retry_longest" and non_null_count == 3:
        best_value, source_label = await _arbitrate_with_gemini(
            field_name, raw_values, rate_limiter
        )

    # Normalize best value and score
    new_normalized = normalize_field(field_name, best_value)
    new_attempt_count = field_data["retry_metadata"]["attempt_count"] + 1

    # If still unresolved after all attempts → pin confidence to 0.0
    if source_label == "unresolved" or new_normalized is None:
        new_confidence = 0.0
        new_display = best_value  # Will be None as per your unresolved example
    else:
        new_confidence = calculate_confidence(source_label, new_normalized, retry_count=new_attempt_count)
        new_display = best_value

    # Update envelope
    updated = dict(field_data)
    updated["display_value"]    = new_display
    updated["normalized_value"] = new_normalized
    updated["source"]           = source_label
    updated["confidence"]       = new_confidence

    # Finalize metadata
    meta["attempted"] = True
    meta["attempt_count"] = new_attempt_count
    meta["retry_outputs"] = retry_outputs_entry  # Keep only the LATEST retry results (3 items)
    updated["retry_metadata"] = meta

    return updated


async def retry_failed_fields(
    company_name: str,
    failed_fields: list[str],
    data: dict,
    agent1_results: dict,
    validation_errors: list[dict],
    rate_limiter: RateLimiter,
) -> dict:
    """
    Retry all fields that:
      - Are non-nullable with null normalized_value, OR
      - Are retryable type (numeric/structured) with null normalized_value

    Processes each field sequentially to respect rate limits.

    Args:
        company_name:      Company being researched.
        failed_fields:     Field names that failed validation.
        data:              Full Stage 3 data dict (163 fields).
        agent1_results:    Raw per-LLM outputs from Agent 1.
        validation_errors: [{field, reason}, ...] from validate_company.
        rate_limiter:      Shared rate limiter.

    Returns:
        Updated data dict with retry results applied.
    """
    # Build a reason map from validation errors
    reason_map: dict[str, str] = {}
    for err in validation_errors:
        field = err.get("field", "")
        if field not in reason_map:
            reason_map[field] = err.get("reason", "failed validation")

    # Identify fields to retry:
    # 1. Any field in failed_fields (caught by validator)
    # 2. Any field where display_value or normalized_value is None (the user wants to "try and get values for null fields")
    all_null_fields = [
        f for f, v in data.items()
        if isinstance(v, dict) and (v.get("display_value") is None or v.get("normalized_value") is None)
    ]

    # Combine and de-duplicate
    fields_to_retry = sorted(list(set(failed_fields) | set(all_null_fields)))

    # Cap retries to avoid 30+ minute runs on free-tier APIs.
    # Prioritize validation failures over null fields.
    MAX_RETRY_FIELDS = 10
    if len(fields_to_retry) > MAX_RETRY_FIELDS:
        # Prioritize: validation failures first, then null fields
        priority = [f for f in fields_to_retry if f in failed_fields]
        rest = [f for f in fields_to_retry if f not in failed_fields]
        fields_to_retry = (priority + rest)[:MAX_RETRY_FIELDS]

    print(f"\n  🔁 Retrying {len(fields_to_retry)} fields (Failed: {len(failed_fields)}, Null: {len(all_null_fields)}, capped to {MAX_RETRY_FIELDS})")

    updated_data = dict(data)  # work on a copy so original is preserved on error

    for field_name in fields_to_retry:
        if field_name not in updated_data:
            continue

        field_data = updated_data[field_name]
        
        # Determine the reason for this specific field retry
        if field_name in reason_map:
            reason = reason_map[field_name]
        elif field_data.get("display_value") is None:
            reason = "field is null (missing from original LLM responses)"
        elif field_data.get("normalized_value") is None:
            reason = "field could not be normalized (unstructured or messy data)"
        else:
            # Should theoretically not happen if logic above is correct
            continue

        print(f"    ↳ [{field_name}] Reason: {reason}")

        try:
            updated_field = await retry_single_field(
                field_name=field_name,
                field_data=field_data,
                company_name=company_name,
                agent1_results=agent1_results,
                validation_reason=reason,
                rate_limiter=rate_limiter,
            )
            updated_data[field_name] = updated_field
        except Exception as e:
            print(f"    ⚠️  Retry failed for [{field_name}]: {e}")
            # Mark as attempted but keep existing value, set confidence to 0
            field_data_copy = dict(field_data)
            field_data_copy["confidence"] = 0.0
            field_data_copy["retry_metadata"] = dict(field_data.get("retry_metadata", {}))
            field_data_copy["retry_metadata"]["attempted"] = True
            field_data_copy["retry_metadata"]["attempt_count"] = (
                field_data.get("retry_metadata", {}).get("attempt_count", 0) + 1
            )
            updated_data[field_name] = field_data_copy

    return updated_data
