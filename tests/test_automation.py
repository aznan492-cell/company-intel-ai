import os
import sys
import asyncio
import pytest

# Add the parent directory to sys.path so we can import from the root module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langgraph_pipeline import run_full_pipeline
from rate_limiter import RateLimiter
from db import SessionLocal, ConsolidatedResult

# This script is designed for Jenkins automation
# It runs a mini-test to ensure the pipeline is "Healthy"

@pytest.mark.asyncio
async def test_pipeline_end_to_end():
    # Force mini mode for speed in CI/CD
    os.environ['TEST_MINI'] = '1'
    
    company = "Accenture"
    print(f"\n🚀 Jenkins CI: Testing pipeline for {company}...")
    
    # 1. Run the actual AI pipeline
    result = await run_full_pipeline(company, RateLimiter(min_interval=1.0))
    
    # 2. Verify we got structured data back
    assert result is not None, "Pipeline returned None"
    assert "stage3" in result, "Result missing Stage 3 data"
    
    # 3. Verify database storage (The most important part for Jenkins)
    if SessionLocal is not None:
        with SessionLocal() as session:
            # Check if Accenture exists in the local Dockerized Postgres
            db_entry = session.query(ConsolidatedResult).filter_by(company_name=company).first()
            
            assert db_entry is not None, f"Data for {company} was NOT saved to the database!"
            
            print(f"✅ Jenkins CI: Validation Passed. Data ID: {db_entry.id}")
    else:
        print("⚠️ Jenkins CI: Skipping DB verification because SessionLocal is None (no DB connection).")

if __name__ == "__main__":
    asyncio.run(test_pipeline_end_to_end())
