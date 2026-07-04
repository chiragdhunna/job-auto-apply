"""End-to-end scheduler loop.

Every ``run_interval_minutes`` (read live from the settings table so dashboard
changes take effect) it runs the full pipeline:

    scrape (ATS boards) -> score new jobs -> apply (ATS / LinkedIn / Indeed)

Resume tailoring + answer generation happen inside the appliers, just before a
submission. Everything respects the platform toggles and score threshold set in
the dashboard. Each cycle's summary is logged to the console and logs/scheduler.log.

Run standalone:
    python -m scheduler.runner            # blocking loop (used by run.sh)
    python -m scheduler.runner --once     # run one cycle and exit
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from backend import config
from backend.db import crud
from backend.db.models import JobSource
from backend.db.session import SessionLocal, init_db
from backend.routers.settings import effective_settings
from backend.scoring.gemini_scorer import score_new_jobs
from backend.scrapers.ats_boards_scraper import run_ats_scrape

logger = logging.getLogger("job_auto_apply.scheduler")

JOB_ID = "pipeline"
_scheduler = None  # set when the loop starts, used for live rescheduling


# --------------------------------------------------------------------------- #
# Logging                                                                      #
# --------------------------------------------------------------------------- #
def _setup_logging() -> None:
    log_dir = Path(config.BASE_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "scheduler.log"
    root = logging.getLogger("job_auto_apply")
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    if not any(getattr(h, "_sched_file", None) == str(log_path) for h in root.handlers):
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        fh._sched_file = str(log_path)  # type: ignore[attr-defined]
        root.addHandler(fh)


# --------------------------------------------------------------------------- #
# Pipeline                                                                     #
# --------------------------------------------------------------------------- #
def _stage(summary: Dict[str, Any], name: str, fn) -> None:
    """Run one pipeline stage, capturing its result or error into the summary."""
    try:
        summary[name] = fn()
    except Exception as exc:  # noqa: BLE001 - one stage must not kill the cycle
        logger.exception("Pipeline stage '%s' failed", name)
        summary[name] = {"error": str(exc)}


def run_pipeline_cycle(db=None) -> Dict[str, Any]:
    own_db = db is None
    if own_db:
        db = SessionLocal()
    summary: Dict[str, Any] = {}
    try:
        settings = effective_settings(db)
        toggles = settings.get("platform_toggles", {})
        logger.info("=== Pipeline cycle start (toggles=%s, threshold=%s) ===",
                    toggles, settings.get("score_threshold"))

        # 1) Scrape ATS boards (respects toggles per source).
        _stage(summary, "scrape", lambda: run_ats_scrape(db, platform_toggles=toggles))

        # 2) Score all new jobs.
        _stage(summary, "score", lambda: score_new_jobs(db))

        # 3) Apply — Greenhouse/Lever via public forms.
        ats_sources = [s for s in (JobSource.GREENHOUSE, JobSource.LEVER) if toggles.get(s, True)]
        if ats_sources:
            from automation.ats_apply import run_ats_applications
            _stage(summary, "ats_apply", lambda: run_ats_applications(db, sources=ats_sources))

        # 4) Apply — LinkedIn Easy Apply.
        if toggles.get(JobSource.LINKEDIN):
            from automation.linkedin_apply import run_linkedin_easy_apply
            _stage(summary, "linkedin", lambda: run_linkedin_easy_apply(db))

        # 5) Apply — Indeed.
        if toggles.get(JobSource.INDEED):
            from automation.indeed_apply import run_indeed_applications
            _stage(summary, "indeed", lambda: run_indeed_applications(db))

        logger.info("=== Pipeline cycle summary === %s", _condense(summary))
    finally:
        if own_db:
            db.close()
    return summary


def _condense(summary: Dict[str, Any]) -> Dict[str, Any]:
    """A compact one-line-ish view: totals found / scored / submitted / failed."""
    scrape = summary.get("scrape", {})
    found = sum(v.get("found", 0) for v in scrape.values() if isinstance(v, dict))
    score = summary.get("score", {}) if isinstance(summary.get("score"), dict) else {}
    submitted = 0
    failed = 0
    for key in ("ats_apply", "linkedin", "indeed"):
        s = summary.get(key)
        if isinstance(s, dict):
            submitted += s.get("submitted", 0)
            failed += s.get("failed", 0)
    return {
        "jobs_found": found,
        "scored": score.get("scored", 0),
        "queued": score.get("queued", 0),
        "submitted": submitted,
        "failed": failed,
    }


# --------------------------------------------------------------------------- #
# Scheduling                                                                   #
# --------------------------------------------------------------------------- #
def _current_interval() -> int:
    db = SessionLocal()
    try:
        return int(crud.get_setting(
            db, "run_interval_minutes", config.keywords_defaults()["run_interval_minutes"]
        ))
    finally:
        db.close()


def _cycle_and_maybe_reschedule() -> None:
    run_pipeline_cycle()
    # Live-apply interval changes made from the dashboard.
    if _scheduler is not None:
        try:
            desired = _current_interval()
            job = _scheduler.get_job(JOB_ID)
            current = getattr(getattr(job, "trigger", None), "interval", None)
            current_min = int(current.total_seconds() // 60) if current else None
            if current_min is not None and desired != current_min:
                logger.info("Run interval changed %s -> %s min; rescheduling.", current_min, desired)
                _scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=desired)
        except Exception:  # noqa: BLE001
            logger.debug("interval reschedule check failed", exc_info=True)


def start(blocking: bool = True, run_now: bool = True):
    """Start the scheduler. Blocking by default (used by run.sh)."""
    global _scheduler
    _setup_logging()
    init_db()
    interval = _current_interval()
    logger.info("Starting scheduler: pipeline every %s minute(s). Active LLM provider: %s",
                interval, config.active_provider_name())

    _scheduler = BlockingScheduler() if blocking else BackgroundScheduler()
    _scheduler.add_job(
        _cycle_and_maybe_reschedule,
        trigger="interval",
        minutes=interval,
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if run_now:
        # Fire the first cycle almost immediately.
        from datetime import datetime, timedelta

        _scheduler.add_job(
            _cycle_and_maybe_reschedule,
            trigger="date",
            run_date=datetime.now() + timedelta(seconds=3),
            id=f"{JOB_ID}_kickoff",
            replace_existing=True,
        )
    _scheduler.start()
    return _scheduler


if __name__ == "__main__":  # pragma: no cover
    import sys

    _setup_logging()
    if "--once" in sys.argv:
        init_db()
        print(_condense(run_pipeline_cycle()))
    else:
        try:
            start(blocking=True, run_now=True)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
