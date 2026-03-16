import asyncio
from main import run_pipeline
from rate_limiter import RateLimiter

async def main():
    # Hardcoded company for verification
    company = "SpaceX"
    print(f"🚀 Starting full LangGraph pipeline for: {company}")
    
    output = await run_pipeline(company)
    
    print("\n" + "=" * 60)
    print("📋 VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"  Company: {output['company']}")
    print(f"  Stage 3 Status: {output['stage3']['validation_report'].get('status', 'fail').upper()}")
    print(f"  Retry Count: {output['stage3']['retry_count']}")

if __name__ == "__main__":
    asyncio.run(main())
