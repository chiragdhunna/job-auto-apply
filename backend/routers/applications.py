"""Applications API — history of submitted / attempted applications.

GET /applications          -> list (joined with job title/company/platform)
GET /applications/{id}     -> one application with parsed custom answers
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import Application
from backend.db.session import get_db

router = APIRouter(prefix="/applications", tags=["applications"])


def _application_to_dict(app: Application) -> Dict[str, Any]:
    job = app.job
    answers: Optional[Dict[str, Any]] = None
    if app.custom_answers_json:
        try:
            answers = json.loads(app.custom_answers_json)
        except json.JSONDecodeError:
            answers = None
    return {
        "id": app.id,
        "job_id": app.job_id,
        "title": job.title if job else None,
        "company": job.company if job else None,
        "platform": job.source if job else None,
        "url": job.url if job else None,
        "status": app.status,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "resume_version_id": app.resume_version_id,
        "platform_response_notes": app.platform_response_notes,
        "custom_answers": answers,
    }


@router.get("")
def list_applications(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [_application_to_dict(a) for a in crud.list_applications(db)]


@router.get("/{app_id}")
def get_application(app_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    app = db.get(Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _application_to_dict(app)
