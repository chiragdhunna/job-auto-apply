"""Jobs API.

GET  /jobs               -> list jobs (filter by status / source)
GET  /jobs/{id}          -> one job (with score details + resume versions)
POST /jobs/scrape        -> run the ATS board scrape now (respects platform toggles)
POST /jobs/{id}/status   -> manual override (approve -> queued, skip -> skipped, ...)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.answer_generator.gemini_answers import generate_answers
from backend.db import crud
from backend.db.models import Job, JobStatus, ResumeVersion
from backend.db.session import get_db
from backend.llm.client import LLMError
from backend.resume_tailor.latex_engine import tailor_and_store
from backend.routers.settings import effective_settings
from backend.scoring.gemini_scorer import score_and_store, score_new_jobs
from backend.scrapers.ats_boards_scraper import run_ats_scrape

import os

router = APIRouter(prefix="/jobs", tags=["jobs"])


def job_to_dict(job: Job, *, include_description: bool = False) -> Dict[str, Any]:
    details = None
    if job.score_details_json:
        try:
            details = json.loads(job.score_details_json)
        except json.JSONDecodeError:
            details = None
    data: Dict[str, Any] = {
        "id": job.id,
        "source": job.source,
        "external_id": job.external_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "salary_range": job.salary_range,
        "discovered_at": job.discovered_at.isoformat() if job.discovered_at else None,
        "fit_score": job.fit_score,
        "score_details": details,
        "status": job.status,
    }
    if include_description:
        data["description_raw"] = job.description_raw
    return data


class StatusUpdate(BaseModel):
    status: str


class AnswersRequest(BaseModel):
    questions: Optional[List[str]] = None
    max_words: int = 150


@router.get("")
def list_jobs(
    status: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    jobs = crud.list_jobs(
        db,
        statuses=[status] if status else None,
        sources=[source] if source else None,
        limit=limit,
    )
    return [job_to_dict(j) for j in jobs]


@router.post("/scrape")
def scrape_now(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Scrape ATS boards + web-wide job boards now."""
    from backend.scrapers.web_boards_scraper import run_web_scrape

    toggles = effective_settings(db)["platform_toggles"]
    summary = run_ats_scrape(db, platform_toggles=toggles)
    summary.update(run_web_scrape(db, platform_toggles=toggles))
    return {"summary": summary}


@router.get("/recommended")
def recommended_jobs(
    min_score: Optional[float] = Query(default=None, ge=0, le=100),
    include_done: bool = Query(default=False, description="Include applied/skipped jobs"),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Scored jobs, best fit first — the jobs worth applying to next.

    A job is flagged `recommended` when its score meets the threshold.
    """
    threshold = float(effective_settings(db)["score_threshold"])
    jobs = crud.list_jobs(db, sources=[source] if source else None, limit=2000)
    out = []
    for j in jobs:
        if j.fit_score is None:
            continue
        if not include_done and j.status in (JobStatus.APPLIED, JobStatus.SKIPPED, JobStatus.FAILED):
            continue
        if min_score is not None and j.fit_score < min_score:
            continue
        d = job_to_dict(j)
        d["recommended"] = j.fit_score >= threshold
        out.append(d)
    out.sort(key=lambda d: (-(d["fit_score"] or 0), d["company"] or ""))
    return out[:limit]


class MarkAppliedRequest(BaseModel):
    note: Optional[str] = None


@router.post("/{job_id}/mark-applied")
def mark_applied(
    job_id: int,
    payload: MarkAppliedRequest = Body(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record that the owner applied to this job manually."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = payload or MarkAppliedRequest()
    rv = crud.latest_resume_version(db, job_id)
    notes = "Marked applied manually by owner"
    if payload.note:
        notes += f": {payload.note}"
    crud.create_application(
        db,
        job_id=job_id,
        resume_version_id=(rv.id if rv else None),
        status="submitted",
        platform_response_notes=notes,
    )
    crud.set_job_status(db, job, JobStatus.APPLIED)
    db.commit()
    return job_to_dict(job)


@router.post("/{job_id}/unmark-applied")
def unmark_applied(job_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Undo an accidental mark-applied: delete the manual record, restore status."""
    from backend.db.models import Application

    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    removed = 0
    for app in list(job.applications):
        if app.platform_response_notes and app.platform_response_notes.startswith(
            "Marked applied manually"
        ):
            db.delete(app)
            removed += 1
    new_status = JobStatus.SCORED if job.fit_score is not None else JobStatus.NEW
    crud.set_job_status(db, job, new_status)
    db.commit()
    data = job_to_dict(job)
    data["removed_manual_records"] = removed
    return data


@router.post("/score")
def score_all_new(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Score every job currently in 'new' status."""
    return score_new_jobs(db)


@router.get("/resume-download/{rv_id}")
def download_resume(rv_id: int, db: Session = Depends(get_db)):
    """Download the compiled PDF for a resume version."""
    rv = db.get(ResumeVersion, rv_id)
    if rv is None:
        raise HTTPException(status_code=404, detail="Resume version not found")
    if not rv.pdf_path or not os.path.exists(rv.pdf_path):
        raise HTTPException(status_code=404, detail="No compiled PDF for this resume version")
    return FileResponse(rv.pdf_path, media_type="application/pdf", filename=os.path.basename(rv.pdf_path))


@router.get("/resume-version/{rv_id}")
def get_resume_version(rv_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Full resume version incl. the LaTeX source (for the dashboard viewer)."""
    rv = db.get(ResumeVersion, rv_id)
    if rv is None:
        raise HTTPException(status_code=404, detail="Resume version not found")
    return {
        "id": rv.id,
        "job_id": rv.job_id,
        "tex_content": rv.tex_content,
        "pdf_path": rv.pdf_path,
        "compiled": bool(rv.pdf_path),
        "generated_at": rv.generated_at.isoformat() if rv.generated_at else None,
    }


@router.post("/{job_id}/resume")
def generate_resume_for_job(
    job_id: int,
    force_tailor: bool = Query(default=False, description="Bypass RESUME_MODE=base_only and tailor via LLM"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate (and compile, if a LaTeX engine is installed) a tailored resume."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        rv = tailor_and_store(db, job, force_tailor=force_tailor)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "resume_version_id": rv.id,
        "job_id": job_id,
        "compiled": bool(rv.pdf_path),
        "pdf_path": rv.pdf_path,
        "tex_chars": len(rv.tex_content or ""),
    }


@router.post("/{job_id}/answers")
def answers_for_job(
    job_id: int,
    payload: AnswersRequest = Body(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Generate answers to the common questions (or a supplied custom set)."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = payload or AnswersRequest()
    try:
        answers = generate_answers(
            job, questions=payload.questions, max_words=payload.max_words
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {exc}") from exc
    return {"job_id": job_id, "answers": answers}


@router.get("/{job_id}/resumes")
def list_job_resumes(job_id: int, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [
        {
            "id": rv.id,
            "pdf_path": rv.pdf_path,
            "compiled": bool(rv.pdf_path),
            "generated_at": rv.generated_at.isoformat(),
            "tex_chars": len(rv.tex_content or ""),
        }
        for rv in crud.list_resume_versions(db, job_id=job_id)
    ]


@router.post("/{job_id}/score")
def score_one(job_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return score_and_store(db, job)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {exc}") from exc


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    data = job_to_dict(job, include_description=True)
    data["resume_versions"] = [
        {"id": rv.id, "pdf_path": rv.pdf_path, "generated_at": rv.generated_at.isoformat()}
        for rv in crud.list_resume_versions(db, job_id=job_id)
    ]
    return data


@router.post("/{job_id}/status")
def set_status(job_id: int, payload: StatusUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if payload.status not in JobStatus.ALL:
        raise HTTPException(status_code=400, detail=f"Invalid status. One of {JobStatus.ALL}")
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    crud.set_job_status(db, job, payload.status)
    db.commit()
    return job_to_dict(job)
