import asyncio
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from schema import CompanyOverview, CompanyCulture, CompanyFinancials
from llm_config import get_gemini_llm, get_groq_llm, get_openrouter_llm
from rate_limiter import RateLimiter
from judge import run_judge
import json
import os

template = """
You are a senior corporate intelligence analyst with access to the latest public data.
Your job is to extract FACTUAL, VERIFIABLE, and PRECISE company intelligence.

STRICT RULES:
1. Return ONLY valid JSON. No explanations, no markdown fences, no commentary.
2. Every value MUST be factual and based on publicly available information (annual reports, SEC filings, press releases, official websites, Glassdoor, LinkedIn, etc.).
3. For numeric fields (revenue, employee count, ratings, percentages), provide EXACT numbers with units and time period (e.g., "$394.3 billion (FY2022)", "164,000 employees (Q4 2023)", "4.2/5.0").
4. For text fields, be SPECIFIC and CONCISE — avoid vague phrases like "generally good" or "varies". Give concrete details.
5. For URLs, provide EXACT working URLs — do not guess or fabricate.
6. If a value is genuinely unknown or not publicly available, return null — do NOT hallucinate or make up data.
7. Prefer the MOST RECENT data available. Always mention the date/period when possible.
8. For list-type fields (competitors, investors, leaders), provide at least 3-5 specific names.

Company Name: {company_name}

Follow this schema exactly:
{format_instructions}
"""

# Shared rate limiter: 4s between calls → max 15 RPM (safe for all free tiers)
rate_limiter = RateLimiter(min_interval=4.0)


async def run_pipeline(company_name):
    """
    Full pipeline orchestrated via LangGraph.
    Covers: Stage 1 (Extract), Stage 2 (Consolidate), Stage 3 (Normalize/Validate/Retry).
    """
    from langgraph_pipeline import run_full_pipeline
    
    # Use the same shared rate limiter
    output = await run_full_pipeline(
        company_name=company_name,
        rate_limiter=rate_limiter
    )

    return output


if __name__ == "__main__":
    company = input("Enter company name: ")

    # Run the full pipeline
    output = asyncio.run(run_pipeline(company))

    # Print summary
    print("\n" + "=" * 60)
    print("📋 FINAL CONSOLIDATED OUTPUT")
    print("=" * 60)
    consolidated = output["consolidated"]
    non_null = sum(1 for v in consolidated.values() if v.get("value") is not None)
    total = len(consolidated)
    print(f"  Fields populated: {non_null}/{total}")

    # Source distribution
    source_counts = {}
    for field_data in consolidated.values():
        src = field_data.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    print("\n  📊 Source Distribution:")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"    {src}: {count} fields")

    # Save full output (includes agent1 raw + consolidated + metadata)
    filename = f"{company.lower().replace(' ', '_')}_intel.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4)
    print(f"\n✅ Full results saved to: {os.path.abspath(filename)}")

    # Save consolidated-only output (with source per field)
    consolidated_filename = f"{company.lower().replace(' ', '_')}_consolidated.json"
    with open(consolidated_filename, "w", encoding="utf-8") as f:
        json.dump(consolidated, f, indent=4)
    print(f"✅ Consolidated output saved to: {os.path.abspath(consolidated_filename)}")

    # Save Stage 3 validated output (full envelope per field)
    stage3 = output.get("stage3", {})
    validated_filename = f"{company.lower().replace(' ', '_')}_validated.json"
    with open(validated_filename, "w", encoding="utf-8") as f:
        json.dump(stage3, f, indent=4)
    print(f"✅ Validated output saved to:    {os.path.abspath(validated_filename)}")

    # Print Stage 3 summary
    val_report = stage3.get("validation_report", {})
    print(f"\n📋 Stage 3 Validation: {val_report.get('status', '?').upper()} "
          f"| {len(val_report.get('errors', []))} error(s) "
          f"| {stage3.get('retry_count', 0)} retry cycle(s)")
