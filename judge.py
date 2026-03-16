"""
Agent 2 — Judge
Consolidates outputs from 3 LLMs into 1 best-of-breed result.

Phase 1: Smart local merge (no LLM call needed)
  - All agree → use that value
  - 2/3 agree → use majority
  - All different → pick longest (most detailed)

Phase 2: LLM judge (only for true conflicts, batched in 1 call)
  - Sends conflicted fields to Gemini for arbitration
  - Only triggered if there are meaningful conflicts
"""

import json
from schema import CompanyIntel, JudgeOutput
from llm_config import get_gemini_llm
from rate_limiter import RateLimiter


# String representations of null that LLMs commonly return
_NULL_STRINGS = frozenset({"null", "none", "n/a", "na", "not available", "not applicable", "unknown", "not found", "not specified", ""})


def _normalize(value):
    """Normalize a field value for comparison."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in _NULL_STRINGS:
        return None
    return v if v else None


def _pick_best_value(field_name: str, values: dict[str, str | None]) -> tuple[str | None, str]:
    """
    Pick the best value for a single field from 3 LLM sources.
    
    Returns:
        (best_value, source_label)
        source_label is one of: "gemini", "groq", "openrouter", "majority", "longest", "only"
    """
    # Collect non-null values with their sources (also filter string "null")
    non_null = {
        src: val for src, val in values.items()
        if val is not None 
        and str(val).strip()
        and str(val).strip().lower() not in _NULL_STRINGS
    }
    
    if not non_null:
        return None, "none"
    
    if len(non_null) == 1:
        src, val = next(iter(non_null.items()))
        return val, src
    
    # Normalize for comparison
    normalized = {src: _normalize(val) for src, val in non_null.items()}
    norm_values = list(normalized.values())
    
    # Check if all non-null values agree
    if len(set(norm_values)) == 1:
        src = next(iter(non_null))
        return non_null[src], "majority"
    
    # Check for 2/3 majority
    from collections import Counter
    counts = Counter(norm_values)
    most_common_val, most_common_count = counts.most_common(1)[0]
    
    if most_common_count >= 2:
        # Find a source with this normalized value
        for src, norm_val in normalized.items():
            if norm_val == most_common_val:
                return non_null[src], "majority"
    
    # All different → pick the longest (most detailed) value
    longest_src = max(non_null, key=lambda src: len(str(non_null[src])))
    return non_null[longest_src], "longest"


def smart_merge(results: dict[str, dict]) -> tuple[dict, dict[str, str], list[str]]:
    """
    Phase 1: Deterministic field-by-field merge across 3 LLM outputs.
    
    Args:
        results: {"gemini": {...}, "groq": {...}, "openrouter": {...}}
    
    Returns:
        (merged_dict, source_map, conflict_fields)
    """
    # Get all possible field names from CompanyIntel
    all_fields = list(CompanyIntel.model_fields.keys())
    sources = list(results.keys())  # e.g. ["gemini", "groq", "openrouter"]
    
    merged = {}
    source_map = {}
    conflict_fields = []
    
    for field in all_fields:
        # Gather this field's value from each source
        values = {}
        for src in sources:
            values[src] = results[src].get(field)
        
        best_value, source_label = _pick_best_value(field, values)
        merged[field] = best_value
        source_map[field] = source_label
        
        # Track fields where all 3 disagree (source_label == "longest")
        if source_label == "longest":
            conflict_fields.append(field)
    
    return merged, source_map, conflict_fields


async def llm_judge_resolve(
    conflict_fields: list[str],
    results: dict[str, dict],
    merged: dict,
    source_map: dict[str, str],
    rate_limiter: RateLimiter,
    max_conflicts_to_judge: int = 30
) -> list[str]:
    """
    Phase 2: Send conflicted fields to LLM for arbitration.
    Batches all conflicts into a single LLM call to save quota.
    
    Returns:
        List of field names that were resolved by the LLM judge.
    """
    if not conflict_fields:
        print("  ✅ No conflicts to resolve — skipping LLM judge.")
        return []
    
    # Limit conflicts to avoid huge prompts
    fields_to_judge = conflict_fields[:max_conflicts_to_judge]
    
    # Build the conflict data for the prompt
    conflicts_data = {}
    for field in fields_to_judge:
        conflicts_data[field] = {
            src: results[src].get(field) for src in results
        }
    
    prompt = f"""You are a corporate intelligence data quality judge.

Below are fields where 3 different AI models gave DIFFERENT answers about a company.
For each field, pick the BEST answer — the one that is most accurate, specific, and useful.

Return ONLY a valid JSON object with this exact structure:
{{
    "field_name": "best_value",
    ...
}}

Do NOT explain. Do NOT wrap in markdown. Return ONLY the JSON.

Conflicting fields and their values from each model:
{json.dumps(conflicts_data, indent=2)}
"""

    try:
        await rate_limiter.wait()
        llm = get_gemini_llm()
        print(f"  🧑‍⚖️  Agent 2 (Judge): Resolving {len(fields_to_judge)} conflicted fields via Gemini...")
        response = await llm.ainvoke(prompt)
        
        # Parse the judge's response
        content = response.content.strip()
        # Remove markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
        
        judge_picks = json.loads(content)
        
        judged_fields = []
        for field, value in judge_picks.items():
            if field in merged:
                merged[field] = value
                source_map[field] = "llm_judge"
                judged_fields.append(field)
        
        print(f"  ✅ Judge resolved {len(judged_fields)} fields.")
        return judged_fields
        
    except Exception as e:
        print(f"  ⚠️  LLM Judge failed: {e}")
        print("  ℹ️  Keeping 'longest' heuristic for conflicted fields.")
        return []


async def run_judge(company_name: str, results: dict[str, dict], rate_limiter: RateLimiter) -> JudgeOutput:
    """
    Full Agent 2 pipeline:
    1. Smart merge (deterministic)
    2. LLM judge (only for conflicts)
    3. Pydantic validation
    
    Args:
        company_name: Name of the company
        results: {"gemini": {...}, "groq": {...}, "openrouter": {...}}
        rate_limiter: Shared rate limiter instance
    
    Returns:
        JudgeOutput with consolidated, validated result
    """
    print("\n" + "=" * 60)
    print("🧑‍⚖️  AGENT 2 — JUDGE (Consolidation)")
    print("=" * 60)
    
    # Phase 1: Smart merge
    print("\n📊 Phase 1: Smart local merge...")
    merged, source_map, conflict_fields = smart_merge(results)
    
    non_null_count = sum(1 for v in merged.values() if v is not None)
    print(f"  ✅ Merged {non_null_count} non-null fields")
    print(f"  🔀 {len(conflict_fields)} fields had all-3-disagree conflicts")
    
    # Phase 2: LLM judge for conflicts
    print("\n🧑‍⚖️  Phase 2: LLM Judge for conflicts...")
    judged_fields = await llm_judge_resolve(
        conflict_fields, results, merged, source_map, rate_limiter
    )
    
    # Phase 3: Pydantic validation
    print("\n✅ Phase 3: Pydantic validation...")
    try:
        consolidated = CompanyIntel(**merged)
        print("  ✅ Pydantic validation passed!")
    except Exception as e:
        print(f"  ⚠️  Pydantic validation issue: {e}")
        print("  ℹ️  Attempting partial construction...")
        # Force construction by filtering to valid fields only
        valid_fields = {k: v for k, v in merged.items() if k in CompanyIntel.model_fields}
        consolidated = CompanyIntel(**valid_fields)
    
    # Build judge output
    judge_output = JudgeOutput(
        company_name=company_name,
        consolidated=consolidated,
        source_map=source_map,
        conflict_fields=conflict_fields,
        llm_judged_fields=judged_fields,
    )
    
    # Print summary
    source_counts = {}
    for src in source_map.values():
        source_counts[src] = source_counts.get(src, 0) + 1
    
    print("\n📊 Source Attribution Summary:")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src}: {count} fields")
    
    return judge_output
