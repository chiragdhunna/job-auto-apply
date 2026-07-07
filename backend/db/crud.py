"""Create/read/update helpers built on top of the ORM models.

These are deliberately small, explicit functions rather than a generic
repository abstraction — they read clearly at the call sites (scrapers,
scorer, scheduler, dashboard).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import (
    Application,
    ApplicationStatus,
    Job,
    JobStatus,
    ResumeVersion,
    Setting,
)

# --------------------------------------------------------------------------- #
# Jobs                                                                         #
# --------------------------------------------------------------------------- #
def upsert_job(db: Session, *, source: str, external_id: str | None, **fields: Any) -> tuple[Job, bool]:
    """Insert a job, or return the existing one (matched on source+external_id).

    Returns (job, created). Existing jobs are NOT overwritten so we never lose a
    fit score / status once a posting has moved through the pipeline.
    """
    existing: Job | None = None
    if external_id is not None:
        existing = db.scalar(
            select(Job).where(Job.source == source, Job.external_id == external_id)
        )
    if existing is None and fields.get("url"):
        # Fallback de-dup on URL when a source has no stable external id.
        existing = db.scalar(select(Job).where(Job.url == fields["url"]))

    if existing is not None:
        return existing, False

    job = Job(source=source, external_id=external_id, **fields)
    db.add(job)
    db.flush()  # populate job.id without ending the transaction
    return job, True


def get_job(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(
    db: Session,
    *,
    statuses: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    limit: int | None = None,
    order_desc: bool = True,
) -> list[Job]:
    stmt = select(Job)
    if statuses:
        stmt = stmt.where(Job.status.in_(list(statuses)))
    if sources:
        stmt = stmt.where(Job.source.in_(list(sources)))
    stmt = stmt.order_by(Job.discovered_at.desc() if order_desc else Job.discovered_at.asc())
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def set_job_status(db: Session, job: Job, status: str) -> Job:
    job.status = status
    db.add(job)
    return job


def set_job_score(
    db: Session,
    job: Job,
    *,
    score: float,
    details: dict[str, Any] | None = None,
    status: str = JobStatus.SCORED,
) -> Job:
    job.fit_score = score
    if details is not None:
        job.score_details_json = json.dumps(details, ensure_ascii=False)
    job.status = status
    db.add(job)
    return job


# --------------------------------------------------------------------------- #
# Resume versions                                                              #
# --------------------------------------------------------------------------- #
def create_resume_version(
    db: Session, *, job_id: int, tex_content: str | None = None, pdf_path: str | None = None
) -> ResumeVersion:
    rv = ResumeVersion(job_id=job_id, tex_content=tex_content, pdf_path=pdf_path)
    db.add(rv)
    db.flush()
    return rv


def latest_resume_version(db: Session, job_id: int) -> ResumeVersion | None:
    return db.scalar(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(ResumeVersion.generated_at.desc())
        .limit(1)
    )


def list_resume_versions(db: Session, *, job_id: int | None = None) -> list[ResumeVersion]:
    stmt = select(ResumeVersion)
    if job_id is not None:
        stmt = stmt.where(ResumeVersion.job_id == job_id)
    stmt = stmt.order_by(ResumeVersion.generated_at.desc())
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Applications                                                                 #
# --------------------------------------------------------------------------- #
def create_application(
    db: Session,
    *,
    job_id: int,
    resume_version_id: int | None = None,
    status: str = ApplicationStatus.PENDING_REVIEW,
    platform_response_notes: str | None = None,
    custom_answers: dict[str, Any] | None = None,
) -> Application:
    app = Application(
        job_id=job_id,
        resume_version_id=resume_version_id,
        status=status,
        platform_response_notes=platform_response_notes,
        custom_answers_json=json.dumps(custom_answers, ensure_ascii=False) if custom_answers else None,
    )
    db.add(app)
    db.flush()
    return app


def list_applications(db: Session) -> list[Application]:
    return list(db.scalars(select(Application).order_by(Application.submitted_at.desc())).all())


# --------------------------------------------------------------------------- #
# Settings (key -> JSON-encoded value)                                         #
# --------------------------------------------------------------------------- #
def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(Setting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return row.value


def set_setting(db: Session, key: str, value: Any) -> Setting:
    encoded = json.dumps(value, ensure_ascii=False)
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=encoded)
        db.add(row)
    else:
        row.value = encoded
        db.add(row)
    return row


def get_all_settings(db: Session, keys: Iterable[str] | None = None) -> dict[str, Any]:
    stmt = select(Setting)
    if keys is not None:
        stmt = stmt.where(Setting.key.in_(list(keys)))
    return {s.key: get_setting(db, s.key) for s in db.scalars(stmt).all()}


# --------------------------------------------------------------------------- #
# Danger zone                                                                  #
# --------------------------------------------------------------------------- #
def clear_all_data(db: Session, *, include_settings: bool = False) -> dict[str, int]:
    """Delete all jobs, applications, and resume versions (FK-safe order).

    Settings (threshold / toggles / interval) survive unless include_settings.
    Returns per-table deletion counts. Callers handle any on-disk PDF cleanup.
    """
    from sqlalchemy import delete, func

    counts = {
        "applications": db.scalar(select(func.count()).select_from(Application)) or 0,
        "resume_versions": db.scalar(select(func.count()).select_from(ResumeVersion)) or 0,
        "jobs": db.scalar(select(func.count()).select_from(Job)) or 0,
        "settings": 0,
    }
    # Children first — SQLite doesn't enforce FK cascades on bulk deletes.
    db.execute(delete(Application))
    db.execute(delete(ResumeVersion))
    db.execute(delete(Job))
    if include_settings:
        counts["settings"] = db.scalar(select(func.count()).select_from(Setting)) or 0
        db.execute(delete(Setting))
    db.commit()
    return counts
