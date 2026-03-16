"""
langgraph_pipeline.py — Full Pipeline Orchestration.
"""

import os
import operator
import asyncio
import json
from typing import TypedDict, Annotated, List, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from schema import CompanyOverview, CompanyCulture, CompanyFinancials
from llm_config import get_gemini_llm, get_groq_llm, get_openrouter_llm
from rate_limiter import RateLimiter
from structure_upgrade import upgrade_structure
from runtime_validator import validate_company
from retry_engine import retry_failed_fields
from field_schema import FIELD_SCHEMA
from judge import run_judge
from web_research import research_company
from db import store_raw_response, store_consolidated_result, is_db_configured

# ── Extraction Utils (from main.py) ───────────────────────────────────────────

EXTRACTION_TEMPLATE = """
You are a senior corporate intelligence analyst with access to the latest public data.
Your job is to extract FACTUAL, VERIFIABLE, and PRECISE company intelligence.

STRICT RULES:
1. Return ONLY valid JSON. No explanations, no markdown fences, no commentary.
2. Every value MUST be factual and based on publicly available information (annual reports, SEC filings, press releases, official websites, Glassdoor, LinkedIn, etc.).
3. For numeric fields (revenue, employee count, ratings, percentages), provide EXACT numbers with units and time period (e.g., "$394.3 billion (FY2022)", "164,000 employees (Q4 2023)", "4.2/5.0").
4. For text fields, be SPECIFIC and CONCISE — avoid vague phrases like "generally good" or "varies". Give concrete details.
5. For URLs, provide EXACT working URLs — do not guess or fabricate.
6. If a value is genuinely unknown, return JSON null — NOT the string "null" or "None" or "N/A". Use actual JSON null.
7. Prefer the MOST RECENT data available. Always mention the date/period when possible.
8. For list-type fields (competitors, investors, leaders), provide at least 3-5 specific names.
9. NEVER return the string "null", "None", "N/A", or "Not Available" as a value. If you don't know, use JSON null.
10. For major public companies, you SHOULD be able to fill MOST fields. Try your best — do not leave fields null unless truly unavailable.

{research_section}

Company Name: {company_name}

Follow this schema exactly:
{format_instructions}
"""

def create_extraction_prompt(pydantic_object, research_context: str = ""):
    parser = PydanticOutputParser(pydantic_object=pydantic_object)
    research_section = ""
    if research_context:
        research_section = (
            "IMPORTANT — Below are REAL, CURRENT search results gathered from the web.\n"
            "Use these as your PRIMARY source of truth. Prefer data from these snippets\n"
            "over your training data whenever they conflict:\n\n"
            f"{research_context}"
        )
    return PromptTemplate(
        template=EXTRACTION_TEMPLATE,
        input_variables=["company_name"],
        partial_variables={
            "format_instructions": parser.get_format_instructions(),
            "research_section": research_section,
        }
    ), parser

async def call_llm_chunk(name, llm, company_name, chunk_name, chunk_model, rate_limiter, research_context=""):
    """Call a single LLM for one schema chunk, respecting rate limits."""
    prompt, parser = create_extraction_prompt(chunk_model, research_context)
    formatted_prompt = prompt.format(company_name=company_name)
    try:
        await rate_limiter.wait()
        response = await llm.ainvoke(formatted_prompt)
        parsed_result = parser.parse(response.content)
        return chunk_name, parsed_result.model_dump()
    except Exception as e:
        print(f"  [{name}] ❌ {chunk_name} failed: {e}")
        return chunk_name, {}

# ── State Definition ──────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    company_name: str
    rate_limiter: RateLimiter
    
    # Stage 0: Web research context
    research_context: str
    
    # Stage 1: Raw outputs per LLM
    agent1_results: dict  # { "gemini": {...}, "groq": {...}, "openrouter": {...} }
    
    # Stage 2: Consolidated metadata
    judge_metadata: dict  # { "conflict_fields": [...], "llm_judged_fields": [...] }
    consolidated_data: dict # { "field_name": { "value": "...", "source": "..." } }
    
    # Stage 3: Core data being transformed (envelopes)
    data: dict
    
    # Status tracking
    retry_count: int
    validation_report: dict
    failed_field_names: List[str]
    null_normalized_fields: List[str]
    status: str


# ── Nodes ───────────────────────────────────────────────────────────────────

async def research_node(state: PipelineState) -> dict:
    """Stage 0: Web Search Grounding."""
    print("\n🔍 [LangGraph] Node: Research (Stage 0)")
    company_name = state["company_name"]
    context = await research_company(company_name)
    return {"research_context": context}


async def extract_node(state: PipelineState) -> dict:
    """Stage 1: Multi-LLM Extraction (with web grounding) — runs LLMs in parallel."""
    print("\n🤖 [LangGraph] Node: Extract (Stage 1)")
    company_name = state["company_name"]
    research_context = state.get("research_context", "")
    
    models = {
        "gemini": get_gemini_llm(),
        "groq": get_groq_llm(),
        "openrouter": get_openrouter_llm(),
    }
    
    import os
    if os.getenv("TEST_MINI") == "1":
        from schema import MiniCompanyOverview
        chunks = {
            "mini_overview": MiniCompanyOverview,
        }
        print("  ⚡ Running in MINI TEST mode (10 fields only)")
    else:
        chunks = {
            "overview": CompanyOverview,
            "culture": CompanyCulture,
            "financials": CompanyFinancials,
        }
    
    async def extract_one_llm(name, llm):
        """Run all 3 chunks for a single LLM (with its own rate limiter)."""
        per_llm_limiter = RateLimiter(min_interval=2.0)
        print(f"  📡 Extraction: {name.upper()}")
        combined = {}
        for chunk_name, chunk_model in chunks.items():
            print(f"    [{name}] {chunk_name}...")
            _, data = await call_llm_chunk(name, llm, company_name, chunk_name, chunk_model, per_llm_limiter, research_context)
            combined.update(data)
        return name, combined
    
    # Run all 3 LLMs in parallel — each has its own rate limiter
    llm_tasks = [extract_one_llm(n, l) for n, l in models.items()]
    llm_results = await asyncio.gather(*llm_tasks)
    
    results = {name: data for name, data in llm_results}
    
    # Store raw responses in database
    if is_db_configured():
        company_name = state["company_name"]
        for name, data in results.items():
            store_raw_response(
                company_name=company_name,
                agent_name="extract_agent",
                model_name=name,
                raw_json=data,
                retry_count=0,
                status="success" if data else "failed",
            )
    
    return {"agent1_results": results}


async def consolidate_node(state: PipelineState) -> dict:
    """Stage 2: Judge Consolidation."""
    print("\n⚖️ [LangGraph] Node: Consolidate (Stage 2)")
    company_name = state["company_name"]
    results = state["agent1_results"]
    rate_limiter = state.get("rate_limiter") or RateLimiter(min_interval=4.0)
    
    judge_output = await run_judge(company_name, results, rate_limiter)
    
    # Build consolidated output with per-field source tracking
    consolidated_with_source = {}
    consolidated_data_raw = judge_output.consolidated.model_dump()
    for field, value in consolidated_data_raw.items():
        consolidated_with_source[field] = {
            "value": value,
            "source": judge_output.source_map.get(field, "unknown"),
        }
    
    return {
        "consolidated_data": consolidated_with_source,
        "judge_metadata": {
            "conflict_fields": judge_output.conflict_fields,
            "llm_judged_fields": judge_output.llm_judged_fields,
        }
    }


def upgrade_node(state: PipelineState) -> dict:
    """Step 1: Upgrade flat consolidated data to full Stage 3 envelopes.
    If data is already pre-populated (e.g. from a test), skip the upgrade.
    """
    # Skip if data was already injected (e.g. from test_retry_demo.py)
    if state.get("data"):
        print("\n📐 [LangGraph] Node: Upgrade — skipped (data pre-populated)")
        return {}

    print("\n📐 [LangGraph] Node: Upgrade")
    data = upgrade_structure(state["consolidated_data"])
    
    non_null_norm = sum(
        1 for v in data.values()
        if isinstance(v, dict) and v.get("normalized_value") is not None
    )
    print(f"  ✅ {len(data)} fields upgraded | {non_null_norm} normalized successfully")
    
    return {"data": data, "retry_count": 0}


def validate_node(state: PipelineState) -> dict:
    """Step 2: Validate the current state of data."""
    print(f"\n✅ [LangGraph] Node: Validate (Attempt {state['retry_count'] + 1})")
    data = state["data"]
    report = validate_company(data)
    
    status = report["status"]
    errors = report["errors"]
    failed_fields = list({e["field"] for e in errors})

    # Find ALL fields that need a retry:
    # Case 1: Fully null — both display_value AND normalized_value are None
    #         (field was missing from ALL LLM responses in Agent 2)
    fully_null = [
        f for f, v in data.items()
        if isinstance(v, dict)
        and v.get("display_value") is None
        and v.get("normalized_value") is None
    ]

    # Case 2: Has a display_value string but normalized_value couldn't be parsed
    #         e.g., "Very positive, around 75" → normalizer returned None
    un_normalizable = [
        f for f, v in data.items()
        if isinstance(v, dict)
        and v.get("normalized_value") is None
        and v.get("display_value") is not None
    ]

    null_normalized = sorted(list(set(fully_null) | set(un_normalizable)))

    print(f"  {'✅' if status == 'pass' else '❌'} Status: {status.upper()}")
    if errors:
        print(f"  ⚠️  {len(errors)} validation error(s)")
    if fully_null:
        print(f"  ❌ {len(fully_null)} field(s) fully null (missing from all LLMs) — will retry")
    if un_normalizable:
        print(f"  🔢 {len(un_normalizable)} field(s) have display_value but null normalized_value — will retry")
        
    return {
        "validation_report": report,
        "status": status,
        "failed_field_names": failed_fields,
        "null_normalized_fields": null_normalized,
    }


async def retry_node(state: PipelineState) -> dict:
    """Step 3: Retry failed/null fields using all 3 LLMs."""
    new_count = state["retry_count"] + 1
    print(f"\n🔁 [LangGraph] Node: Retry ({new_count}/2)")

    # Combine: validation failures + fields that couldn't be normalized
    all_targets = sorted(list(
        set(state["failed_field_names"]) | set(state.get("null_normalized_fields", []))
    ))
    print(f"  Targets: {len(state['failed_field_names'])} validation fail(s) + "
          f"{len(state.get('null_normalized_fields', []))} un-normalized field(s)")
    
    rate_limiter = state.get("rate_limiter") or RateLimiter(min_interval=4.0)
    
    updated_data = await retry_failed_fields(
        company_name=state["company_name"],
        failed_fields=all_targets,
        data=state["data"],
        agent1_results=state["agent1_results"],
        validation_errors=state["validation_report"]["errors"],
        rate_limiter=rate_limiter
    )
    
    return {"data": updated_data, "retry_count": new_count}


def end_node(state: PipelineState) -> dict:
    """Final Step: Cleanup and summary."""
    print("\n🏁 [LangGraph] Node: End")
    
    data = state["data"]
    report = state["validation_report"]
    retry_count = state["retry_count"]
    
    _print_stage3_summary(data, report, retry_count)
    
    # Auto-save to filesystem (useful for runs started from Studio UI)
    company_safe = state["company_name"].lower().replace(" ", "_")
    filename = f"{company_safe}_validated.json"
    
    output_to_save = {
        "data":              data,
        "validation_report": report,
        "retry_count":       retry_count,
    }
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output_to_save, f, indent=4)
    print(f"  ✅ Final output saved to: {os.path.abspath(filename)}")
    
    # Store consolidated result in database
    if is_db_configured():
        store_consolidated_result(
            company_name=state["company_name"],
            normalized_data=output_to_save,
            retry_attempts=retry_count,
            validation_status=report.get("status", "unknown"),
        )
    
    return {}


# ── Conditional Logic ─────────────────────────────────────────────────────────

def should_retry(state: PipelineState) -> str:
    """
    Decide whether to retry or finish.
    Retry if:
      - Validation failed (non-nullable fields are null / cross-field violated), OR
      - Any field has a display_value but null normalized_value (failed to parse)
    Stop only when max cycles exhausted OR everything is clean.
    """
    if state["retry_count"] >= 2:
        return "end"

    has_validation_errors = state["status"] == "fail"
    has_null_normalized    = len(state.get("null_normalized_fields", [])) > 0

    if has_validation_errors or has_null_normalized:
        return "retry"

    return "end"


# ── Graph Construction ────────────────────────────────────────────────────────

def create_pipeline_graph():
    workflow = StateGraph(PipelineState)
    
    # Add nodes
    workflow.add_node("research", research_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("consolidate", consolidate_node)
    workflow.add_node("upgrade", upgrade_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("retry", retry_node)
    workflow.add_node("end", end_node)
    
    # Set entry point — start with web research
    workflow.set_entry_point("research")
    
    # Connect nodes
    workflow.add_edge("research", "extract")
    workflow.add_edge("extract", "consolidate")
    workflow.add_edge("consolidate", "upgrade")
    workflow.add_edge("upgrade", "validate")
    
    workflow.add_conditional_edges(
        "validate",
        should_retry,
        {
            "retry": "retry",
            "end": "end"
        }
    )
    
    workflow.add_edge("retry", "validate")
    workflow.add_edge("end", END)
    
    return workflow.compile()


# ── Public API ───────────────────────────────────────────────────────────────

async def run_full_pipeline(
    company_name: str,
    rate_limiter: RateLimiter,
) -> dict:
    """Wrapper to run the Full LangGraph Pipeline (Stage 1 to 3)."""
    print("🔬  FULL COMPANY INTEL PIPELINE — LANGGRAPH")
    print("=" * 60)

    # Visual confirmation for LangSmith tracing
    if os.getenv("LANGCHAIN_TRACING_V2") == "true":
        project = os.getenv("LANGCHAIN_PROJECT", "default")
        print(f"📡 [LangSmith] Tracing active: project='{project}'")
    
    graph = create_pipeline_graph()
    
    initial_state = {
        "company_name": company_name,
        "rate_limiter": rate_limiter,
        "research_context": "",
        "agent1_results": {},
        "consolidated_data": {},
        "judge_metadata": {},
        "data": {},
        "retry_count": 0,
        "validation_report": {},
        "failed_field_names": [],
        "null_normalized_fields": [],
        "status": ""
    }
    
    final_state = await graph.ainvoke(initial_state)
    
    return {
        "company":           company_name,
        "agent1_results":    final_state["agent1_results"],
        "consolidated":      final_state["consolidated_data"],
        "judge_metadata":    final_state["judge_metadata"],
        "stage3": {
            "data":              final_state["data"],
            "validation_report": final_state["validation_report"],
            "retry_count":       final_state["retry_count"],
        }
    }


def _print_stage3_summary(data: dict, report: dict, retry_count: int) -> None:
    """Print summary (copied from original pipeline.py for consistency)."""
    total = len(FIELD_SCHEMA)
    populated = sum(1 for v in data.values() if v.get("display_value") is not None)
    avg_conf = sum(v["confidence"] for v in data.values()) / total
    
    print("\n" + "─" * 60)
    print("📊  LANGGRAPH STAGE 3 SUMMARY")
    print("─" * 60)
    print(f"  Fields total:       {total}")
    print(f"  Fields populated:   {populated}/{total}")
    print(f"  Avg confidence:     {avg_conf:.3f}")
    print(f"  Retry cycles used:  {retry_count}/2")
    print(f"  Final status:       {report.get('status', '?').upper()}")
    print("─" * 60)
