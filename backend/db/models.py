"""SQLAlchemy ORM models for job-auto-apply.

Schema (SQLite):
  jobs             - discovered job postings + fit score + pipeline status
  applications     - a submitted (or attempted) application for a job
  resume_versions  - JD-tailored resume artifacts (.tex + compiled PDF path)
  settings         - key/value store (JSON-encoded values) for runtime config

Note: ``typing.Optional`` (rather than ``X | None``) is used for the mapped
annotations so the models import cleanly on Python 3.9+ as well as the
3.11+ target — SQLAlchemy evaluates these annotations at mapper-config time.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base shared by every model."""


def utcnow() -> dt.datetime:
    """Timezone-naive UTC timestamp (SQLite stores naive datetimes)."""
    return dt.datetime.utcnow()


# --------------------------------------------------------------------------- #
# Status vocabularies (kept as plain strings for flexibility / easy querying)  #
# --------------------------------------------------------------------------- #
class JobStatus:
    NEW = "new"
    SCORED = "scored"
    QUEUED = "queued"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"

    ALL = (NEW, SCORED, QUEUED, APPLIED, FAILED, SKIPPED, NEEDS_REVIEW)


class ApplicationStatus:
    SUBMITTED = "submitted"
    FAILED = "failed"
    PENDING_REVIEW = "pending_review"

    ALL = (SUBMITTED, FAILED, PENDING_REVIEW)


class JobSource:
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"

    ALL = (LINKEDIN, INDEED, GREENHOUSE, LEVER, WORKDAY, ASHBY)


# --------------------------------------------------------------------------- #
# Models                                                                       #
# --------------------------------------------------------------------------- #
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, default=None)
    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str] = mapped_column(String(255), index=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    url: Mapped[str] = mapped_column(Text)
    description_raw: Mapped[Optional[str]] = mapped_column(Text, default=None)
    salary_range: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    discovered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    fit_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    # Pragmatic extension of the spec: keep the scorer's reasoning/matched
    # skills/gaps JSON alongside the numeric fit_score so the dashboard can
    # explain *why* a job scored the way it did.
    score_details_json: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.NEW, index=True)

    applications: Mapped[List["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    resume_versions: Mapped[List["ResumeVersion"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    # A posting is uniquely identified by its source + external id. NULL
    # external_ids are treated as distinct by SQLite, which is what we want.
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Job {self.id} {self.source}:{self.title} @ {self.company} [{self.status}]>"


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    tex_content: Mapped[Optional[str]] = mapped_column(Text, default=None)
    pdf_path: Mapped[Optional[str]] = mapped_column(Text, default=None)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped["Job"] = relationship(back_populates="resume_versions")
    applications: Mapped[List["Application"]] = relationship(back_populates="resume_version")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ResumeVersion {self.id} job={self.job_id} pdf={self.pdf_path}>"


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL"), default=None
    )
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default=ApplicationStatus.PENDING_REVIEW, index=True)
    platform_response_notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    custom_answers_json: Mapped[Optional[str]] = mapped_column(Text, default=None)

    job: Mapped["Job"] = relationship(back_populates="applications")
    resume_version: Mapped[Optional["ResumeVersion"]] = relationship(back_populates="applications")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application {self.id} job={self.job_id} [{self.status}]>"


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON-encoded scalar / object

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.key}={self.value!r}>"
