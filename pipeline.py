"""
pipeline.py — Stage 3 async orchestration loop.

Flow:
    upgrade_structure  →  validate_company
                              │
                    pass ─────┘
                              │
                    fail ─────→  retry_failed_fields (if retry_count < 2)
                                       │
                                 validate_company  (loop)
                                       │
                             fail + retry_count >= 2 → END

Returns:
    {
        "data": {field: full_envelope, ...},  # all 163 fields
        "validation_report": {"status": ..., "errors": [...]},
        "retry_count": int,
    }
"""

import asyncio
from rate_limiter import RateLimiter
from structure_upgrade import upgrade_structure
from runtime_validator import validate_company
from retry_engine import retry_failed_fields
from field_schema import FIELD_SCHEMA

MAX_RETRY_CYCLES = 2


async def run_stage3(
    company_name: str,
    agent1_results: dict,
    consolidated_data: dict,
    rate_limiter: RateLimiter,
) -> dict:
    """
    Execute the full Stage 3 pipeline for one company.

    Args:
        company_name:      Company being researched.
        agent1_results:    {"gemini": {...}, "groq": {...}, "openrouter": {...}}
                           Raw per-LLM field values from Agent 1.
        consolidated_data: Agent 2 output: {field: {"value": ..., "source": ...}}
        rate_limiter:      Shared rate limiter instance.

    Returns:
        {"data": ..., "validation_report": ..., "retry_count": int}
    """
    print("\n" + "=" * 60)
    print("🔬  STAGE 3 — VALIDATION, NORMALIZATION & RETRY")
    print("=" * 60)

    # ── Step 1: Structure Upgrade ─────────────────────────────────────────────
    print("\n📐 Step 1: Upgrading field structure...")
    data = upgrade_structure(consolidated_data)
    non_null_norm = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("normalized_value") is not None
    )
    print(f"  ✅ {len(data)} fields upgraded | {non_null_norm} normalized successfully")

    # ── Steps 2–4: Validate → Retry loop ─────────────────────────────────────
    retry_count = 0
    validation_report: dict = {}

    while True:
        # Validate
        print(f"\n✅ Step {'2' if retry_count == 0 else str(retry_count + 2)}: "
              f"Validating (attempt {retry_count + 1})...")
        validation_report = validate_company(data)

        status = validation_report["status"]
        errors = validation_report["errors"]

        print(f"  {'✅' if status == 'pass' else '❌'} Status: {status.upper()}")
        if errors:
            print(f"  ⚠️  {len(errors)} validation error(s):")
            for err in errors[:10]:       # Show first 10
                print(f"    • [{err['field']}] {err['reason']}")
            if len(errors) > 10:
                print(f"    ... and {len(errors) - 10} more")

        # Exit conditions
        if status == "pass":
            print("\n  🎉 Validation passed!")
            break

        if retry_count >= MAX_RETRY_CYCLES:
            print(f"\n  ⛔ Max retry cycles ({MAX_RETRY_CYCLES}) reached — stopping.")
            # Freeze confidence at 0.0 for still-failing fields
            failed_field_names = {e["field"] for e in errors}
            for field_name in failed_field_names:
                if field_name in data and isinstance(data[field_name], dict):
                    entry = data[field_name]
                    if entry["retry_metadata"]["attempt_count"] >= MAX_RETRY_CYCLES:
                        data[field_name]["confidence"] = 0.0
            break

        # Retry
        retry_count += 1
        failed_field_names = list({e["field"] for e in errors})
        print(f"\n🔁 Retry cycle {retry_count}/{MAX_RETRY_CYCLES} "
              f"— {len(failed_field_names)} field(s) to retry...")

        data = await retry_failed_fields(
            company_name=company_name,
            failed_fields=failed_field_names,
            data=data,
            agent1_results=agent1_results,
            validation_errors=errors,
            rate_limiter=rate_limiter,
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_stage3_summary(data, validation_report, retry_count)

    return {
        "data":              data,
        "validation_report": validation_report,
        "retry_count":       retry_count,
    }


def _print_stage3_summary(data: dict, validation_report: dict, retry_count: int) -> None:
    """Print a concise Stage 3 summary to STDOUT."""
    total = len(FIELD_SCHEMA)
    populated = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("display_value") is not None
    )
    normalized_count = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("normalized_value") is not None
    )
    avg_conf = (
        sum(v["confidence"] for v in data.values() if isinstance(v, dict))
        / total
    )
    retried = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("retry_metadata", {}).get("attempted")
    )

    print("\n" + "─" * 60)
    print("📊  STAGE 3 SUMMARY")
    print("─" * 60)
    print(f"  Fields total:       {total}")
    print(f"  Fields populated:   {populated}/{total}")
    print(f"  Fields normalized:  {normalized_count}/{total}")
    print(f"  Avg confidence:     {avg_conf:.3f}")
    print(f"  Fields retried:     {retried}")
    print(f"  Retry cycles used:  {retry_count}/{2}")
    print(f"  Final status:       {validation_report.get('status', '?').upper()}")
    print("─" * 60)
