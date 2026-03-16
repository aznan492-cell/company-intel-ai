"""
web_research.py — Web search grounding for Company Intelligence Pipeline.
Uses DuckDuckGo to gather current, factual data about a company
before passing to LLMs for extraction.
"""

import asyncio
from duckduckgo_search import DDGS


# ── Search Queries ────────────────────────────────────────────────────────────

SEARCH_TOPICS = [
    {
        "label": "Financials",
        "query": '"{company}" revenue valuation funding annual report 2024',
    },
    {
        "label": "People & Culture",
        "query": '"{company}" employees glassdoor rating culture reviews',
    },
    {
        "label": "Leadership",
        "query": '"{company}" CEO founder leadership team board of directors',
    },
    {
        "label": "Products & Market",
        "query": '"{company}" products competitors market share industry',
    },
    {
        "label": "Overview",
        "query": '"{company}" headquarters founded overview company profile',
    },
]


# ── Core Function ─────────────────────────────────────────────────────────────

async def research_company(company_name: str, max_results_per_query: int = 5) -> str:
    """
    Search the web for current company information.
    
    Args:
        company_name: Name of the company to research.
        max_results_per_query: Number of search results per topic.
    
    Returns:
        A formatted string of research context to inject into LLM prompts.
    """
    print(f"\n🔍 [Research] Searching the web for: {company_name}")
    
    all_snippets = []
    
    def _search_topic(topic: dict) -> list[dict]:
        """Run a single search (sync, for thread pool)."""
        query = topic["query"].replace("{company}", company_name)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results_per_query))
                return results
        except Exception as e:
            print(f"  ⚠️  Search failed for '{topic['label']}': {e}")
            return []
    
    # Run searches concurrently using thread pool (DDGS is sync)
    loop = asyncio.get_event_loop()
    tasks = []
    for topic in SEARCH_TOPICS:
        task = loop.run_in_executor(None, _search_topic, topic)
        tasks.append((topic["label"], task))
    
    for label, task in tasks:
        try:
            results = await task
            if results:
                print(f"  ✅ {label}: {len(results)} results")
                for r in results:
                    snippet = f"[{label}] {r.get('title', '')}: {r.get('body', '')}"
                    all_snippets.append(snippet)
            else:
                print(f"  ⚠️  {label}: no results")
        except Exception as e:
            print(f"  ❌ {label}: {e}")
    
    if not all_snippets:
        print("  ⚠️  No web results found. LLMs will rely on training data only.")
        return ""
    
    # Build formatted context
    context = f"=== WEB RESEARCH RESULTS FOR: {company_name.upper()} ===\n\n"
    context += "\n\n".join(all_snippets)
    context += f"\n\n=== END OF WEB RESEARCH ({len(all_snippets)} snippets) ==="
    
    print(f"  📄 Total: {len(all_snippets)} snippets collected")
    
    return context
