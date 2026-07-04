"""FastAPI application entrypoint.

Run with:  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

import logging

from backend.db.session import init_db
from backend.routers import applications as applications_router
from backend.routers import debug as debug_router
from backend.routers import jobs as jobs_router
from backend.routers import settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Ensure the schema exists before serving any request.
    init_db()
    yield


app = FastAPI(
    title="job-auto-apply",
    version="0.1.0",
    description="Local, fully-automated job application system.",
    lifespan=lifespan,
)

app.include_router(settings_router.router)
app.include_router(jobs_router.router)
app.include_router(applications_router.router)
app.include_router(debug_router.router)


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness probe used by run.sh and the dashboard."""
    return {"status": "ok"}
