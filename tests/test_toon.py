import asyncio
from langchain_core.prompts import PromptTemplate
from llm_config import get_gemini_llm

TOON_PROMPT = """You are an expert business analyst extraction tool.
Extract the following 5 overview fields for the company: {company}. 

Output the extraction ONLY in Token-Oriented Object Notation (TOON) format.
Do NOT use JSON braces, quotes (unless a string contains a comma or newline), or trailing commas.

Schema:
name (string)
incorporation_year (string)
headquarters_address (string)
office_count (string)
website_url (string)

Example TOON Output format (using Microsoft as an example):
name: Microsoft Corporation
incorporation_year: 1975
headquarters_address: Redmond, Washington
office_count: ~200
website_url: https://www.microsoft.com

Ensure every key matches exactly. If you do not know a value, output: null
Return ONLY the TOON formatted text without markdown backticks.
"""

def parse_simple_toon(toon_text: str) -> dict:
    """Very naive TOON parser for flat objects."""
    result = {}
    lines = toon_text.strip().split("\n")
    for line in lines:
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.lower() == "null":
                val = None
            result[key] = val
    return result

async def test_toon_extraction():
    company = "Airbnb"
    print(f"\n🚀 Testing TOON Extraction for: {company}")
    print("=" * 60)
    
    llm = get_gemini_llm()
    prompt = PromptTemplate.from_template(TOON_PROMPT)
    chain = prompt | llm
    
    print("\n⏳ Calling LLM (expecting TOON)...")
    response = await chain.ainvoke({"company": company})
    raw_text = response.content.replace("```toon", "").replace("```text", "").replace("```", "").strip()
    
    print("\n" + "=" * 60)
    print("RAW TOON OUTPUT FROM LLM (Token Saving!):")
    print("=" * 60)
    print(raw_text)
    
    print("\n" + "=" * 60)
    print("PARSED TO PYTHON DICTIONARY:")
    print("=" * 60)
    parsed_dict = parse_simple_toon(raw_text)
    import json
    print(json.dumps(parsed_dict, indent=2))

if __name__ == "__main__":
    asyncio.run(test_toon_extraction())
