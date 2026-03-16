"""
server.py — FastAPI backend for Company Intelligence Pipeline.
Pure REST API — no frontend. Interactive docs at /docs (Swagger UI).
"""

import os
import uuid
import json
import asyncio
import sys
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ── App Setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Company Intelligence API",
    description=(
        "AI-powered company analysis API. "
        "Enter a company name and get a comprehensive intelligence report "
        "covering 163 fields across financials, culture, leadership, strategy, and more.\n\n"
        "**Pipeline stages:** Research → Extract → Consolidate → Validate → Retry"
    ),
    version="1.0.0",
)

# In-memory job store
jobs: dict[str, dict] = {}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Request / Response Models ─────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    company_name: str = Field(..., min_length=1, examples=["SpaceX", "Google", "Tesla"])


class AnalyzeResponse(BaseModel):
    job_id: str
    company_name: str
    status: str = "queued"
    message: str = "Pipeline started. Poll /api/status/{job_id} for progress."


class StatusResponse(BaseModel):
    job_id: str
    company_name: str
    status: str
    current_stage: str
    progress_log: list[str] = Field(default_factory=list, description="Recent log messages")
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class HistoryItem(BaseModel):
    filename: str
    company: str
    timestamp: str
    fields_populated: int | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    output_dir: str
    total_analyses: int


# ── Progress Capture ──────────────────────────────────────────────────────────

class ProgressCapture:
    """Captures print() output from the pipeline."""
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.messages: list[str] = []
        self._original_stdout = None

    def write(self, text: str):
        if text.strip():
            self.messages.append(text.strip())
            if "[LangGraph] Node:" in text:
                node_name = text.split("Node:")[1].strip().split("(")[0].strip()
                jobs[self.job_id]["current_stage"] = node_name
        if self._original_stdout:
            self._original_stdout.write(text)

    def flush(self):
        if self._original_stdout:
            self._original_stdout.flush()


# ── Pipeline Runner ───────────────────────────────────────────────────────────

async def run_pipeline_job(job_id: str, company_name: str):
    """Run the full pipeline in the background, capturing progress."""
    from langgraph_pipeline import run_full_pipeline
    from rate_limiter import RateLimiter

    jobs[job_id]["status"] = "running"
    jobs[job_id]["started_at"] = datetime.now().isoformat()

    capture = ProgressCapture(job_id)
    capture._original_stdout = sys.stdout
    jobs[job_id]["capture"] = capture
    sys.stdout = capture

    try:
        rate_limiter = RateLimiter(min_interval=4.0)
        result = await run_full_pipeline(
            company_name=company_name,
            rate_limiter=rate_limiter,
        )

        # Save result to disk
        safe_name = company_name.lower().replace(" ", "_")
        filename = OUTPUT_DIR / f"{safe_name}_{job_id[:8]}.json"
        clean_result = json.loads(json.dumps(result, default=str))

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(clean_result, f, indent=4)

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = clean_result
        jobs[job_id]["output_file"] = str(filename)
        jobs[job_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        capture.messages.append(f"Pipeline failed: {e}")
    finally:
        sys.stdout = capture._original_stdout


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check if the API is running and healthy."""
    total = len(list(OUTPUT_DIR.glob("*.json")))
    return HealthResponse(
        output_dir=str(OUTPUT_DIR),
        total_analyses=total,
    )


@app.post("/api/analyze", response_model=AnalyzeResponse, tags=["Pipeline"])
async def start_analysis(req: AnalyzeRequest):
    """
    Start a new company intelligence analysis.

    The pipeline runs in the background. Use the returned `job_id`
    to poll for status and retrieve results.
    """
    company = req.company_name.strip()

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "company_name": company,
        "status": "queued",
        "current_stage": "Queued",
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        "output_file": None,
    }

    asyncio.create_task(run_pipeline_job(job_id, company))

    return AnalyzeResponse(job_id=job_id, company_name=company)


@app.get("/api/status/{job_id}", response_model=StatusResponse, tags=["Pipeline"])
async def get_status(
    job_id: str,
    last_n_logs: int = Query(default=20, ge=1, le=200, description="Number of recent log lines to return"),
):
    """
    Poll the current status and progress of a running pipeline.

    Returns the current stage, recent log messages, and timing info.
    Call this repeatedly (e.g. every 2 seconds) until `status` is `completed` or `failed`.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    capture = job.get("capture")
    logs = capture.messages[-last_n_logs:] if capture else []

    return StatusResponse(
        job_id=job["job_id"],
        company_name=job["company_name"],
        status=job["status"],
        current_stage=job.get("current_stage", ""),
        progress_log=logs,
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        error=job.get("error"),
    )


@app.get("/api/result/{job_id}", tags=["Pipeline"])
async def get_result(job_id: str):
    """
    Get the complete intelligence report for a finished analysis.

    Returns the full JSON with all 163 fields, confidence scores,
    sources, and validation status.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {job.get('error')}")
    if job["status"] != "completed":
        return JSONResponse(
            status_code=202,
            content={"status": job["status"], "message": "Pipeline still running. Poll /api/status for progress."}
        )

    return job["result"]


@app.get("/api/download/{job_id}", tags=["Pipeline"])
async def download_result(job_id: str):
    """Download the completed analysis as a `.json` file."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if not job.get("output_file"):
        raise HTTPException(status_code=404, detail="No output file yet — pipeline may still be running")

    filepath = Path(job["output_file"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")

    return FileResponse(
        str(filepath),
        media_type="application/json",
        filename=filepath.name,
    )


@app.get("/api/history", response_model=list[HistoryItem], tags=["History"])
async def get_history():
    """List the most recent 20 completed analyses."""
    history = []
    for f in sorted(OUTPUT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                stage3 = data.get("stage3", {})
                d = stage3.get("data", {})
                populated = sum(1 for v in d.values() if isinstance(v, dict) and v.get("display_value") is not None)
                history.append(HistoryItem(
                    filename=f.name,
                    company=data.get("company", f.stem),
                    timestamp=datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    fields_populated=populated if populated else None,
                ))
        except Exception:
            pass
    return history[:20]


@app.get("/api/history/{filename}", tags=["History"])
async def get_history_item(filename: str):
    """Retrieve a specific past analysis by filename."""
    filepath = OUTPUT_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".json":
        raise HTTPException(status_code=404, detail="File not found")

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    from db import init_db
    
    print("🚀 Company Intel API starting at http://localhost:8000")
    print("📖 Swagger docs at        http://localhost:8000/docs")
    
    # Initialize database tables
    init_db()
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
