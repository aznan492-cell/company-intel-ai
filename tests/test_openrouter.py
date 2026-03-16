import asyncio
import json
from llm_config import get_openrouter_llm
from main import call_llm_all_chunks

async def test_openrouter():
    company = input("Enter company name to test OpenRouter: ")
    if not company:
        company = "Accenture"
        
    print(f"\n🚀 Testing OpenRouter (Gemma-2-9B) for company: {company}")
    print("=" * 60)
    
    llm = get_openrouter_llm()
    
    try:
        # call_llm_all_chunks is imported from main.py and handles 
        # the 3-chunk sequential extraction (Overview, Culture, Financials)
        name, results = await call_llm_all_chunks("openrouter", llm, company)
        
        print("\n" + "=" * 60)
        print(f"✅ OpenRouter Results Extraction Complete")
        print("=" * 60)
        
        # Count populated fields
        populated = sum(1 for v in results.values() if v is not None)
        total = len(results)
        print(f"  Fields populated: {populated}/{total}")
        
        # Save to temp file
        filename = "openrouter_test_output.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
            
        print(f"  Sample data (first 5 fields):")
        sample = {k: results[k] for k in list(results.keys())[:5]}
        print(json.dumps(sample, indent=4))
        print(f"\nFull raw output saved to: {filename}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_openrouter())
