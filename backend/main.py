"""FastAPI application entrypoint.

Run with:  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.db.session import init_db
from backend.routers import settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health", tags=["system"])
def health() -> dict:
    """Liveness probe used by run.sh and the dashboard."""
    return {"status": "ok"}
