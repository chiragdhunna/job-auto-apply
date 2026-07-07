"""Automated application submission for Greenhouse & Lever public forms.

Flow per queued job:
  1. Ensure a compiled, JD-tailored resume PDF exists (generate one if not).
  2. Generate answers to any free-text questions found on the form.
  3. Fill name / email / phone / resume upload / custom questions with human-like
     typing and randomised delays, in a non-headless persistent browser context.
  4. Submit (unless AUTOMATION_DRY_RUN=true) and record the outcome in the
     applications table; update the job status.

ATS DOMs change frequently — selectors are tried from fallback lists and every
action is logged to logs/automation.log so breakages are diagnosable.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from automation.stealth_config import (
    applicant_from_resume,
    first_locator,
    human_click,
    human_delay,
    human_type,
    launch_persistent_context,
    long_delay,
    setup_automation_logging,
    short_delay,
    type_phone,
)
from backend import config
from backend.answer_generator.gemini_answers import _slug, generate_answers
from backend.db import crud
from backend.db.models import ApplicationStatus, Job, JobSource, JobStatus
from backend.llm.client import LLMError
from backend.resume_tailor.latex_engine import tailor_and_store

logger = logging.getLogger("jobctl.automation.ats")

# Selector fallback lists (ordered by preference).
GH_SELECTORS = {
    "first_name": ["#first_name", 'input[name="first_name"]', 'input[autocomplete="given-name"]'],
    "last_name": ["#last_name", 'input[name="last_name"]', 'input[autocomplete="family-name"]'],
    "email": ["#email", 'input[type="email"]', 'input[name="email"]'],
    "phone": [
        "#phone",
        'input[type="tel"]',
        'input[name="phone"]',
        'input[id*="phone" i]',
        'input[name*="phone" i]',
        'input[aria-label*="phone" i]',
        'input[autocomplete="tel"]',
    ],
    "submit": ['#submit_app', 'button[type="submit"]', 'text="Submit Application"'],
}
LEVER_SELECTORS = {
    "name": ['input[name="name"]', "#name"],
    "email": ['input[name="email"]', 'input[type="email"]'],
    "phone": [
        'input[name="phone"]',
        'input[type="tel"]',
        'input[id*="phone" i]',
        'input[aria-label*="phone" i]',
        'input[autocomplete="tel"]',
    ],
    "submit": ['button[type="submit"]', 'text="Submit application"', ".template-btn-submit"],
}
SUCCESS_HINTS = [
    "text=Thank you",
    "text=application has been submitted",
    "text=successfully",
    "text=We received your application",
]


# --------------------------------------------------------------------------- #
# Resume / helpers                                                             #
# --------------------------------------------------------------------------- #
def _ensure_resume_pdf(
    db: Session, job: Job, base_resume_data: Dict[str, Any]
) -> Tuple[Optional[str], Optional[int]]:
    """Return (pdf_path, resume_version_id) for the job, generating if needed.

    Raises LLMError when the LLM provider is down/timing out — the caller aborts
    the whole batch in that case (retrying job after job would just burn one
    timeout per job).
    """
    rv = crud.latest_resume_version(db, job.id)
    if rv and rv.pdf_path and os.path.exists(rv.pdf_path):
        return rv.pdf_path, rv.id
    logger.info("No compiled resume for job %s — generating one.", job.id)
    try:
        rv = tailor_and_store(db, job, base_resume_data)
    except LLMError:
        raise  # provider outage/timeout — let the caller stop the batch
    except Exception:  # noqa: BLE001
        logger.exception("Resume generation failed for job %s", job.id)
        return None, (rv.id if rv else None)
    if rv and rv.pdf_path and os.path.exists(rv.pdf_path):
        return rv.pdf_path, rv.id
    return None, (rv.id if rv else None)


def _detect_platform(url: str) -> Optional[str]:
    u = (url or "").lower()
    if "greenhouse.io" in u or "grnh.se" in u:
        return JobSource.GREENHOUSE
    if "lever.co" in u:
        return JobSource.LEVER
    return None


def _platform_for_job(job: Job) -> Optional[str]:
    """Platform to apply through — trust the scraper's source first.

    Many companies (Databricks, Stripe, ...) configure CUSTOM career-site URLs
    in Greenhouse, so URL sniffing misses them. The `source` column recorded at
    scrape time is authoritative; URL detection is only a fallback for jobs
    that arrived without an ATS source.
    """
    if job.source in (JobSource.GREENHOUSE, JobSource.LEVER):
        return job.source
    return _detect_platform(job.url)


def _enter_greenhouse_form(page) -> None:
    """Get onto the actual Greenhouse application form.

    Custom career sites embed the form in an iframe (#grnhse_iframe pointing at
    a greenhouse.io embed URL). Our selectors can't reach inside an iframe —
    so when no form fields are present on the top-level page, find the embed
    iframe and navigate DIRECTLY to its URL (a full-page version of the form).
    """
    if first_locator(page, GH_SELECTORS["first_name"]) or first_locator(page, GH_SELECTORS["email"]):
        return  # already on a form
    for sel in ("iframe#grnhse_iframe", 'iframe[src*="greenhouse.io"]', 'iframe[src*="greenhouse"]'):
        try:
            frame_el = page.locator(sel).first
            if frame_el.count() > 0:
                src = frame_el.get_attribute("src")
                if src:
                    logger.info(
                        "Greenhouse embed iframe detected — opening the form directly: %s",
                        src[:120],
                    )
                    page.goto(src, wait_until="domcontentloaded", timeout=45000)
                    human_delay(1.5, 3.0)
                    return
        except Exception:
            logger.debug("Greenhouse embed check failed for %s", sel, exc_info=True)
    logger.info("No Greenhouse form fields or embed iframe found on this page.")


def _set_resume_file(page, resume_path: str) -> bool:
    for sel in ['input[type="file"]']:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.set_input_files(resume_path)
                short_delay()
                logger.info("Uploaded resume: %s", os.path.basename(resume_path))
                return True
        except Exception:
            logger.debug("resume upload via %s failed", sel, exc_info=True)
    logger.warning("Could not find a file input to upload the resume.")
    return False


def _label_for(textarea) -> Optional[str]:
    for attr in ("aria-label", "placeholder", "name"):
        try:
            val = textarea.get_attribute(attr)
            if val and len(val.strip()) > 3:
                return val.strip()
        except Exception:
            continue
    return None


def _answer_free_text(page, job: Job, base_resume_data: Dict[str, Any]) -> Dict[str, str]:
    """Best-effort: fill visible textareas with grounded generated answers."""
    filled: Dict[str, str] = {}
    try:
        textareas = page.locator("textarea")
        count = textareas.count()
    except Exception:
        return filled
    targets = []
    questions: List[str] = []
    for i in range(count):
        ta = textareas.nth(i)
        try:
            if not ta.is_visible():
                continue
        except Exception:
            continue
        q = _label_for(ta)
        if q:
            targets.append((i, q))
            questions.append(q)
    if not questions:
        return filled
    try:
        answers = generate_answers(job, base_resume_data=base_resume_data, questions=questions)
    except Exception:  # noqa: BLE001
        logger.exception("Answer generation failed for job %s", job.id)
        return filled
    for i, q in targets:
        ans = answers.get(_slug(q))
        if ans:
            try:
                human_type(textareas.nth(i), ans)
                filled[q] = ans
            except Exception:
                logger.debug("Could not fill textarea %d", i, exc_info=True)
    return filled


# --------------------------------------------------------------------------- #
# Form fillers                                                                 #
# --------------------------------------------------------------------------- #
def fill_greenhouse(page, applicant, resume_path, job, base_resume_data) -> Dict[str, str]:
    for field, key in (("first_name", "first_name"), ("last_name", "last_name"),
                       ("email", "email")):
        loc = first_locator(page, GH_SELECTORS[field])
        if loc and applicant.get(key):
            human_type(loc, applicant[key])
    phone_loc = first_locator(page, GH_SELECTORS["phone"])
    if phone_loc and applicant.get("phone"):
        type_phone(phone_loc, applicant["phone"])
    elif not phone_loc:
        logger.warning("Greenhouse form: no phone field matched the selectors.")
    _set_resume_file(page, resume_path)
    return _answer_free_text(page, job, base_resume_data)


def fill_lever(page, applicant, resume_path, job, base_resume_data) -> Dict[str, str]:
    loc = first_locator(page, LEVER_SELECTORS["name"])
    if loc and applicant.get("full_name"):
        human_type(loc, applicant["full_name"])
    loc = first_locator(page, LEVER_SELECTORS["email"])
    if loc and applicant.get("email"):
        human_type(loc, applicant["email"])
    phone_loc = first_locator(page, LEVER_SELECTORS["phone"])
    if phone_loc and applicant.get("phone"):
        type_phone(phone_loc, applicant["phone"])
    elif not phone_loc:
        logger.warning("Lever form: no phone field matched the selectors.")
    _set_resume_file(page, resume_path)
    return _answer_free_text(page, job, base_resume_data)


def _looks_submitted(page) -> bool:
    for sel in SUCCESS_HINTS:
        try:
            if page.locator(sel).first.count() > 0:
                return True
        except Exception:
            continue
    return False


# --------------------------------------------------------------------------- #
# Per-job application                                                          #
# --------------------------------------------------------------------------- #
def apply_to_job(page, job, applicant, resume_path, base_resume_data, dry_run) -> Tuple[str, str, Dict[str, str]]:
    """Returns (application_status, notes, answers_filled)."""
    platform = _platform_for_job(job)
    if platform is None:
        return (
            ApplicationStatus.PENDING_REVIEW,
            f"Not a Greenhouse/Lever job (source={job.source}, url={job.url})",
            {},
        )

    target_url = job.url
    if platform == JobSource.LEVER and not target_url.rstrip("/").endswith("/apply"):
        target_url = target_url.rstrip("/") + "/apply"

    logger.info("Applying to job %s (%s): %s", job.id, platform, target_url)
    page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
    human_delay(1.5, 3.5)

    # Greenhouse embedded boards sometimes need an "Apply" click to reveal the form.
    apply_btn = first_locator(page, ['text="Apply"', 'text="Apply for this job"', "a#apply_button"])
    if apply_btn:
        try:
            human_click(apply_btn)
            human_delay(1.0, 2.5)
        except Exception:
            pass

    if platform == JobSource.GREENHOUSE:
        # Custom career domains (databricks.com, ...) embed the form in an iframe.
        _enter_greenhouse_form(page)
        answers = fill_greenhouse(page, applicant, resume_path, job, base_resume_data)
    else:
        answers = fill_lever(page, applicant, resume_path, job, base_resume_data)

    human_delay(1.0, 2.5)

    if dry_run:
        return ApplicationStatus.PENDING_REVIEW, "DRY RUN — form filled, not submitted", answers

    submit = first_locator(
        page, GH_SELECTORS["submit"] if platform == JobSource.GREENHOUSE else LEVER_SELECTORS["submit"]
    )
    if not submit:
        return ApplicationStatus.PENDING_REVIEW, "Submit button not found; needs manual review", answers

    human_click(submit)
    human_delay(2.5, 5.0)

    if _looks_submitted(page):
        return ApplicationStatus.SUBMITTED, f"Submitted via {platform}", answers
    return (
        ApplicationStatus.PENDING_REVIEW,
        f"Clicked submit on {platform} but no confirmation detected — verify manually",
        answers,
    )


# --------------------------------------------------------------------------- #
# Run                                                                          #
# --------------------------------------------------------------------------- #
def run_ats_applications(
    db: Session,
    max_per_run: Optional[int] = None,
    dry_run: Optional[bool] = None,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply to queued Greenhouse/Lever jobs (up to the per-run cap).

    ``sources`` restricts which platforms are applied to (used by the scheduler
    to honour platform toggles); defaults to both Greenhouse and Lever.
    """
    setup_automation_logging()
    from playwright.sync_api import sync_playwright  # local import: heavy dep

    base_resume_data = config.load_base_resume_data()
    applicant = applicant_from_resume(base_resume_data)
    cap = max_per_run or config.MAX_APPLICATIONS_PER_RUN
    dry_run = config.AUTOMATION_DRY_RUN if dry_run is None else dry_run
    src = sources or [JobSource.GREENHOUSE, JobSource.LEVER]

    queued = crud.list_jobs(db, statuses=[JobStatus.QUEUED], sources=src, order_desc=True)
    jobs = queued[:cap]
    summary = {"attempted": 0, "submitted": 0, "failed": 0, "needs_review": 0,
               "eligible": len(queued), "dry_run": dry_run}
    if not jobs:
        logger.info("No queued Greenhouse/Lever jobs to apply to.")
        return summary

    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False)
        page = context.new_page()
        try:
            for job in jobs:
                summary["attempted"] += 1
                try:
                    resume_path, rv_id = _ensure_resume_pdf(db, job, base_resume_data)
                except LLMError as exc:
                    # Provider down or timing out: every subsequent job would burn a
                    # full timeout too. Stop the batch; jobs stay 'queued' and are
                    # retried automatically next cycle.
                    logger.error(
                        "LLM unavailable while generating resume for job %s: %s "
                        "— stopping this application batch; remaining jobs stay "
                        "queued for the next cycle.",
                        job.id,
                        exc,
                    )
                    summary["llm_error"] = str(exc)
                    summary["attempted"] -= 1
                    break
                if not resume_path:
                    crud.set_job_status(db, job, JobStatus.NEEDS_REVIEW)
                    db.commit()
                    summary["needs_review"] += 1
                    if rv_id:
                        logger.warning(
                            "Job %s -> needs_review: resume LaTeX was generated but "
                            "PDF compilation failed — install `tectonic` or `pdflatex` "
                            "and re-queue (Approve) the job.",
                            job.id,
                        )
                    else:
                        logger.warning(
                            "Job %s -> needs_review: resume generation failed "
                            "(see logs/automation.log for the traceback).",
                            job.id,
                        )
                    continue
                try:
                    app_status, notes, answers = apply_to_job(
                        page, job, applicant, resume_path, base_resume_data, dry_run
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Application failed for job %s", job.id)
                    app_status, notes, answers = ApplicationStatus.FAILED, f"Exception: {exc}", {}

                crud.create_application(
                    db, job_id=job.id, resume_version_id=rv_id, status=app_status,
                    platform_response_notes=notes, custom_answers=answers or None,
                )
                if app_status == ApplicationStatus.SUBMITTED:
                    crud.set_job_status(db, job, JobStatus.APPLIED)
                    summary["submitted"] += 1
                elif app_status == ApplicationStatus.FAILED:
                    crud.set_job_status(db, job, JobStatus.FAILED)
                    summary["failed"] += 1
                else:
                    crud.set_job_status(db, job, JobStatus.NEEDS_REVIEW)
                    summary["needs_review"] += 1
                db.commit()
                long_delay()  # space out applications to avoid rate-based detection
        finally:
            context.close()

    logger.info("ATS application run complete: %s", summary)
    return summary
