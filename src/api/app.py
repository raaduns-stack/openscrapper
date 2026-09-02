import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from src.models.criteria import SearchCriteria
from src.pipeline import LeadDiscoveryPipeline

app = FastAPI(title="Scrappee API")

JOBS: dict[str, dict] = {}


@app.get("/health")
def health():
    return {"status": "ok"}


async def _run_job(job_id: str, criteria: SearchCriteria):
    try:
        JOBS[job_id]["status"] = "running"

        pipeline = LeadDiscoveryPipeline(max_pages=25)
        leads = await pipeline.run(criteria)

        output = Path(f"output/{job_id}.csv")
        pipeline.run_and_export  # keep export capability available
        from src.exports.csv_export import export_csv
        export_csv(leads, str(output))

        JOBS[job_id].update(
            status="completed",
            lead_count=len(leads),
            output=str(output),
        )
    except Exception as exc:
        JOBS[job_id].update(
            status="failed",
            error=str(exc),
        )


@app.post("/jobs", status_code=202)
async def create_job(criteria: SearchCriteria):
    job_id = uuid.uuid4().hex

    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "lead_count": 0,
    }

    asyncio.create_task(_run_job(job_id, criteria))

    return JOBS[job_id]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed")

    output = Path(job["output"])

    if not output.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        output,
        media_type="text/csv",
        filename=f"scrappee-{job_id}.csv",
    )
