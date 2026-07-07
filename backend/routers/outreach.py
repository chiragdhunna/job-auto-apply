"""Outreach API — DRAFT-ONLY by design.

No endpoint here sends anything, ever. `mark-sent` records that the OWNER sent
a message themselves; it is a status write. There is deliberately no send
endpoint, no send toggle, and none should be added — see backend/outreach/.

GET  /outreach                                   -> overview rows for dashboard
GET  /outreach/{job_id}                          -> contact + drafts for a job
POST /outreach/{job_id}/regenerate               -> (re)generate contact + drafts
PUT  /outreach/{job_id}/contact                  -> owner manually sets contact
PUT  /outreach/{job_id}/draft/{draft_id}         -> save owner's edits
PUT  /outreach/{job_id}/draft/{draft_id}/mark-sent -> owner marks manually sent
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db import crud
from backend.db.models import JobStatus, OutreachDraft
from backend.db.session import get_db
from backend.llm.client import LLMError
from backend.outreach.contact_finder import find_contact
from backend.outreach.message_drafter import draft_messages

router = APIRouter(prefix="/outreach", tags=["outreach"])


# --------------------------------------------------------------------------- #
# Serialization                                                                #
# --------------------------------------------------------------------------- #
def _contact_dict(c) -> Optional[Dict[str, Any]]:
    if c is None:
        return None
    return {
        "id": c.id, "job_id": c.job_id, "name": c.name, "title": c.title,
        "linkedin_url": c.linkedin_url, "email": c.email,
        "source": c.source, "confidence": c.confidence,
        "found_at": c.found_at.isoformat() if c.found_at else None,
    }


def _draft_dict(d: OutreachDraft) -> Dict[str, Any]:
    return {
        "id": d.id, "job_id": d.job_id, "contact_id": d.contact_id,
        "channel": d.channel, "draft_text": d.draft_text, "subject": d.subject,
        "status": d.status,
        "generated_at": d.generated_at.isoformat() if d.generated_at else None,
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
    }


# --------------------------------------------------------------------------- #
# Generation service (also used by the scheduler stage)                        #
# --------------------------------------------------------------------------- #
def generate_outreach_for_job(db: Session, job) -> Dict[str, Any]:
    """Identify a contact and create both drafts for a job.

    Raises LLMError when the provider is unavailable. Generation is the FINAL
    automated step — the results only ever surface in the dashboard.
    """
    contact_data = find_contact(job)
    contact = crud.upsert_outreach_contact(db, job.id, **contact_data)

    applied_at = None
    if job.status == JobStatus.APPLIED and job.applications:
        latest = max(job.applications, key=lambda a: a.submitted_at or dt.datetime.min)
        if latest.submitted_at:
            applied_at = latest.submitted_at.strftime("%Y-%m-%d")

    result = draft_messages(job, contact=contact_data, applied_at=applied_at)

    drafts = [
        crud.create_outreach_draft(
            db, job_id=job.id, contact_id=contact.id, channel="linkedin_message",
            draft_text=result["linkedin"]["text"], status=result["linkedin"]["status"],
        ),
        crud.create_outreach_draft(
            db, job_id=job.id, contact_id=contact.id, channel="email",
            draft_text=result["email"]["text"], subject=result["email"]["subject"],
            status=result["email"]["status"],
        ),
    ]
    db.commit()
    return {"contact": _contact_dict(contact), "drafts": [_draft_dict(d) for d in drafts]}


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #
@router.get("")
def outreach_overview(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Jobs worth reaching out about (queued/recommended or applied) + draft state."""
    return crud.jobs_with_outreach_state(db, [JobStatus.QUEUED, JobStatus.APPLIED])


@router.get("/{job_id}")
def get_outreach(job_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    contact = crud.get_outreach_contact(db, job_id)
    drafts = crud.list_outreach_drafts(db, job_id)
    return {
        "job_id": job_id, "title": job.title, "company": job.company, "url": job.url,
        "job_status": job.status,
        "contact": _contact_dict(contact),
        "drafts": [_draft_dict(d) for d in drafts],
    }


@router.post("/{job_id}/regenerate")
def regenerate(job_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """(Re)generate the contact + both drafts. Never sends anything."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return generate_outreach_for_job(db, job)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Drafting failed: {exc}") from exc


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None


@router.put("/{job_id}/contact")
def set_contact_manually(job_id: int, payload: ContactUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Owner supplies/edits the contact themselves (source=manual)."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")
    contact = crud.upsert_outreach_contact(
        db, job_id, **fields, source="manual",
        confidence="high" if payload.name else "none",
    )
    db.commit()
    return _contact_dict(contact)


class DraftUpdate(BaseModel):
    draft_text: Optional[str] = None
    subject: Optional[str] = None


def _get_draft(db: Session, job_id: int, draft_id: int) -> OutreachDraft:
    draft = db.get(OutreachDraft, draft_id)
    if draft is None or draft.job_id != job_id:
        raise HTTPException(status_code=404, detail="Draft not found for this job")
    return draft


@router.put("/{job_id}/draft/{draft_id}")
def save_draft_edits(job_id: int, draft_id: int, payload: DraftUpdate,
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    draft = _get_draft(db, job_id, draft_id)
    if payload.draft_text is not None:
        draft.draft_text = payload.draft_text
    if payload.subject is not None:
        draft.subject = payload.subject
    if draft.status in ("draft", "needs_owner_input"):
        draft.status = "edited"
    db.add(draft)
    db.commit()
    return _draft_dict(draft)


@router.put("/{job_id}/draft/{draft_id}/mark-sent")
def mark_sent(job_id: int, draft_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Bookkeeping ONLY: records that the owner sent this themselves.

    This endpoint does not (and must never) trigger any actual sending.
    """
    draft = _get_draft(db, job_id, draft_id)
    draft.status = "sent"
    draft.sent_at = dt.datetime.utcnow()
    db.add(draft)
    db.commit()
    return _draft_dict(draft)


@router.put("/{job_id}/draft/{draft_id}/skip")
def skip_draft(job_id: int, draft_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    draft = _get_draft(db, job_id, draft_id)
    draft.status = "skipped"
    db.add(draft)
    db.commit()
    return _draft_dict(draft)
