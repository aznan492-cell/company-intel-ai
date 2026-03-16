"""
test_retry_demo.py — Integration test to visually demonstrate retry logic.

Uses a small, hand-crafted dataset with 6 fields:
  - 2 fields that are healthy (won't retry)
  - 2 fields with display_value but NULL normalized_value  → triggers un-normalized retry
  - 2 fields that are fully NULL                          → triggers null-field retry

Runs through the real LangGraph pipeline with real LLM calls.
"""

import asyncio
import json
from rate_limiter import RateLimiter
from langgraph_pipeline import run_stage3_langgraph

# ── 1. A SMALL mock consolidated_data (6 fields only) ────────────────────────
#
# Normally Agent 2 outputs {field: {value: ..., source: ...}} for ALL 163 fields.
# Here we only provide 6, and the rest will be filled as null by upgrade_structure().
#
MOCK_CONSOLIDATED = {
    # ✅ HEALTHY — should NOT be retried
    "name": {
        "value": "Apple Inc.",
        "source": "majority"
    },
    "incorporation_year": {
        "value": "1976",
        "source": "majority"
    },

    # 🔶 HAS display_value BUT un-normalizable — triggers "un-normalized" retry
    "brand_sentiment_score": {
        "value": "Very positive, around 75 out of 100",   # normalizer can't extract a number
        "source": "groq"
    },
    "market_share_percentage": {
        "value": "Dominant player, roughly 18 percent of global smartphone market",  # can't extract %
        "source": "longest"
    },

    # ❌ FULLY NULL — triggers "null field" retry
    "glassdoor_rating": {
        "value": None,
        "source": "missing"
    },
    "annual_revenue": {
        "value": None,
        "source": "missing"
    },
}

# ── 2. Mock Agent 1 results (per-model raw values for previous_values capture) ─
MOCK_AGENT1 = {
    "gemini": {
        "brand_sentiment_score": "75/100",
        "market_share_percentage": "~18%",
        "glassdoor_rating": None,
        "annual_revenue": None,
    },
    "groq": {
        "brand_sentiment_score": "Very positive sentiment, around 75",
        "market_share_percentage": "Dominant player with roughly 18 percent",
        "glassdoor_rating": "4.0",          # groq had it, but was overridden during merge
        "annual_revenue": "$383 billion",
    },
    "openrouter": {
        "brand_sentiment_score": "75",
        "market_share_percentage": "18%",
        "glassdoor_rating": None,
        "annual_revenue": None,
    },
}


async def main():
    print("\n" + "=" * 60)
    print("🧪 RETRY LOGIC DEMO — 6 fields, real LLM calls, real retries")
    print("=" * 60)
    print("\nFields under test:")
    print("  ✅ [name]                — healthy, skip retry")
    print("  ✅ [incorporation_year]  — healthy, skip retry")
    print("  🔶 [brand_sentiment_score]  — display_value but un-normalized → RETRY")
    print("  🔶 [market_share_percentage] — display_value but un-normalized → RETRY")
    print("  ❌ [glassdoor_rating]   — fully null → RETRY")
    print("  ❌ [annual_revenue]     — fully null → RETRY")
    print()

    rate_limiter = RateLimiter(min_interval=4.0)  # 4s between calls = 15 RPM

    from normalizer import normalize_field
    from confidence import calculate_confidence

    def _envelope(field_name: str, display_value, source: str) -> dict:
        """Build a Stage 3 envelope for a single field inline."""
        nv = normalize_field(field_name, display_value)
        return {
            "display_value":    display_value,
            "normalized_value": nv,
            "source":           source,
            "confidence":       calculate_confidence(source, nv, 0),
            "retry_metadata": {
                "attempted":       False,
                "attempt_count":   0,
                "previous_values": [],
                "retry_outputs":   [],
            },
        }

    # Build ONLY the 6 demo fields (skip upgrade_structure to avoid 160 null retries)
    data = {
        "name":                   _envelope("name", "Apple Inc.", "majority"),
        "incorporation_year":      _envelope("incorporation_year", "1976", "majority"),
        "brand_sentiment_score":   _envelope("brand_sentiment_score",
                                             "Very positive, around 75 out of 100", "groq"),
        "market_share_percentage": _envelope("market_share_percentage",
                                             "Dominant player, roughly 18 percent", "longest"),
        "glassdoor_rating":        _envelope("glassdoor_rating", None, "missing"),
        "annual_revenue":          _envelope("annual_revenue",   None, "missing"),
    }

    print("🔍 Initial field states:")
    for f, v in data.items():
        nv = v["normalized_value"]
        dv = v["display_value"]
        symbol = "✅" if nv is not None else ("🔶" if dv else "❌")
        print(f"  {symbol} [{f}] display={repr(dv)} | normalized={nv}")
    print()

    # Run the graph with a pre-built data dict (bypasses upgrade node)
    result = await run_stage3_langgraph(
        company_name="Apple Inc.",
        agent1_results=MOCK_AGENT1,
        consolidated_data=MOCK_CONSOLIDATED,
        rate_limiter=rate_limiter,
        initial_data=data,         # Inject our 6-field dict directly
    )

    # ── Pretty-print the 6 fields ─────────────────────────────────────
    fields_of_interest = [
        "name", "incorporation_year",
        "brand_sentiment_score", "market_share_percentage",
        "glassdoor_rating", "annual_revenue",
    ]
    print("\n" + "=" * 60)
    print("📋 FINAL STATE OF 6 TEST FIELDS")
    print("=" * 60)
    output = {f: result["data"].get(f, "NOT FOUND") for f in fields_of_interest}
    print(json.dumps(output, indent=2))

    print(f"\n🔁 Retry cycles used: {result['retry_count']}/2")
    print(f"📊 Final validation:   {result['validation_report'].get('status', '?').upper()}")

    with open("retry_demo_output.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\n✅ Output saved to retry_demo_output.json")


if __name__ == "__main__":
    asyncio.run(main())
