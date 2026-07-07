"""Automated LinkedIn Easy Apply (with heightened stealth).

IMPORTANT — session handling:
  * Log in to LinkedIn ONCE, manually, in the persistent browser profile
    (run `python -m automation.linkedin_apply --login`). We deliberately do NOT
    automate the login form, which is the biggest "new device / suspicious"
    trigger. Subsequent runs reuse the saved cookies/session.

Because LinkedIn has no public API, discovery happens in the same authenticated
browser session: we search for the target roles (Easy-Apply-filtered), read each
posting, score it via the LLM, and only run the multi-step Easy Apply flow for
jobs that clear the score threshold.

Extra caution vs. the ATS applier: longer randomised delays (3-8s), mouse
movement before clicks, and a hard per-run application cap.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
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
    wait_for_manual_login,
)
from backend import config
from backend.answer_generator.gemini_answers import _slug, generate_answers
from backend.db import crud
from backend.db.models import ApplicationStatus, JobSource, JobStatus
from backend.llm.client import LLMError
from backend.resume_tailor.latex_engine import tailor_and_store
from backend.scoring.gemini_scorer import score_and_store

logger = logging.getLogger("job_auto_apply.automation.linkedin")

FEED_URL = "https://www.linkedin.com/feed/"
JOBS_SEARCH = "https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}&f_AL=true"
MAX_EASY_APPLY_STEPS = 12


class LinkedInAuthError(RuntimeError):
    """Raised when the persistent profile is not logged in to LinkedIn."""


# --------------------------------------------------------------------------- #
# Session                                                                      #
# --------------------------------------------------------------------------- #
def _is_logged_in(page) -> bool:
    page.goto(FEED_URL, wait_until="domcontentloaded", timeout=45000)
    human_delay(2.0, 4.0)
    url = page.url.lower()
    if "login" in url or "authwall" in url or "checkpoint" in url:
        return False
    # Login form present => not authenticated.
    if first_locator(page, ["input#session_key", 'input[name="session_key"]']):
        return False
    return True


def open_for_manual_login() -> None:
    """Open a browser so the owner can log in once; the session then persists."""
    setup_automation_logging()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False)
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        wait_for_manual_login(context, "LinkedIn")
        try:
            context.close()
        except Exception:
            pass  # user already closed the window — session is saved


# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #
def _collect_job_urls(page, role: str, location: str, limit: int) -> List[str]:
    url = JOBS_SEARCH.format(
        kw=urllib.parse.quote(role), loc=urllib.parse.quote(location)
    )
    logger.info("LinkedIn search: %s @ %s", role, location)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    human_delay(2.5, 5.0)
    # Scroll the results pane to load more cards.
    for _ in range(3):
        page.mouse.wheel(0, 1600)
        human_delay(1.0, 2.5)
    hrefs: List[str] = []
    try:
        anchors = page.locator('a.job-card-container__link, a.job-card-list__title, a[href*="/jobs/view/"]')
        count = min(anchors.count(), limit)
        for i in range(count):
            href = anchors.nth(i).get_attribute("href")
            if href:
                if href.startswith("/"):
                    href = "https://www.linkedin.com" + href
                hrefs.append(href.split("?")[0])
    except Exception:
        logger.debug("Could not enumerate job cards", exc_info=True)
    # de-dup preserving order
    seen = set()
    return [h for h in hrefs if not (h in seen or seen.add(h))]


def _read_job(page, url: str) -> Optional[Dict[str, Any]]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_delay(2.0, 4.0)
        # Expand "see more" description if present.
        more = first_locator(page, ['button:has-text("See more")', "button.show-more-less-html__button"])
        if more:
            try:
                human_click(more)
            except Exception:
                pass
        title = _text(page, ["h1", ".job-details-jobs-unified-top-card__job-title"])
        company = _text(page, [".job-details-jobs-unified-top-card__company-name", "a.topcard__org-name-link"])
        location = _text(page, [".job-details-jobs-unified-top-card__primary-description-container", ".topcard__flavor--bullet"])
        description = _text(page, ["#job-details", ".jobs-description__content", ".show-more-less-html__markup"])
        external_id = None
        if "/jobs/view/" in url:
            external_id = url.rstrip("/").split("/jobs/view/")[-1].split("/")[0]
        if not title:
            return None
        return {
            "external_id": external_id,
            "title": title,
            "company": company or "Unknown",
            "location": location,
            "url": url,
            "description_raw": description,
        }
    except Exception:
        logger.debug("Failed to read job at %s", url, exc_info=True)
        return None


def _text(page, selectors: List[str]) -> Optional[str]:
    loc = first_locator(page, selectors)
    if loc:
        try:
            return (loc.inner_text() or "").strip()
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------- #
# Easy Apply flow                                                              #
# --------------------------------------------------------------------------- #
def _fill_visible_step(page, job, base_resume_data, resume_path, applicant) -> Dict[str, str]:
    filled: Dict[str, str] = {}
    # Resume upload, if the step offers it.
    try:
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0 and resume_path:
            file_input.set_input_files(resume_path)
            short_delay()
    except Exception:
        pass
    # Phone / plain text inputs that are empty.
    try:
        inputs = page.locator('input[type="text"], input[type="tel"], input[type="email"]')
        for i in range(inputs.count()):
            el = inputs.nth(i)
            if not el.is_visible():
                continue
            if (el.input_value() or "").strip():
                continue
            label = (el.get_attribute("aria-label") or el.get_attribute("name") or "").lower()
            if "phone" in label or "mobile" in label:
                type_phone(el, applicant.get("phone", ""))
            elif "email" in label:
                human_type(el, applicant.get("email", ""))
            elif "city" in label or "location" in label:
                human_type(el, applicant.get("location", ""))
    except Exception:
        logger.debug("text input fill issue", exc_info=True)
    # Free-text questions -> grounded answers.
    try:
        textareas = page.locator("textarea")
        qs, targets = [], []
        for i in range(textareas.count()):
            ta = textareas.nth(i)
            if not ta.is_visible():
                continue
            q = ta.get_attribute("aria-label") or ta.get_attribute("name")
            if q:
                qs.append(q)
                targets.append((i, q))
        if qs:
            answers = generate_answers(job, base_resume_data=base_resume_data, questions=qs)
            for i, q in targets:
                a = answers.get(_slug(q))
                if a:
                    human_type(textareas.nth(i), a)
                    filled[q] = a
    except Exception:
        logger.debug("textarea fill issue", exc_info=True)
    return filled


def easy_apply_flow(page, job, resume_path, base_resume_data, applicant, dry_run) -> Tuple[str, str, Dict[str, str]]:
    btn = first_locator(page, [
        'button.jobs-apply-button',
        'button[aria-label*="Easy Apply"]',
        'button:has-text("Easy Apply")',
    ])
    if not btn:
        return ApplicationStatus.PENDING_REVIEW, "No Easy Apply button (external apply?)", {}
    human_click(btn)
    human_delay(1.5, 3.5)

    answers: Dict[str, str] = {}
    for step in range(MAX_EASY_APPLY_STEPS):
        answers.update(_fill_visible_step(page, job, base_resume_data, resume_path, applicant))
        human_delay(1.0, 2.5)

        submit = first_locator(page, [
            'button[aria-label="Submit application"]',
            'button:has-text("Submit application")',
        ])
        if submit:
            if dry_run:
                _dismiss_modal(page)
                return ApplicationStatus.PENDING_REVIEW, "DRY RUN — reached submit, not clicked", answers
            human_click(submit)
            human_delay(2.0, 4.0)
            return ApplicationStatus.SUBMITTED, "Submitted via LinkedIn Easy Apply", answers

        nxt = first_locator(page, [
            'button[aria-label="Continue to next step"]',
            'button[aria-label="Review your application"]',
            'button:has-text("Next")',
            'button:has-text("Review")',
        ])
        if not nxt:
            break
        human_click(nxt)
        human_delay(1.5, 3.5)

    _dismiss_modal(page)
    return ApplicationStatus.PENDING_REVIEW, "Could not complete Easy Apply steps automatically", answers


def _dismiss_modal(page) -> None:
    try:
        close = first_locator(page, ['button[aria-label="Dismiss"]', 'button[aria-label="Close"]'])
        if close:
            human_click(close)
            human_delay(0.5, 1.5)
            discard = first_locator(page, ['button:has-text("Discard")'])
            if discard:
                human_click(discard)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Discovery only (no applying) — used by the recommendation pipeline           #
# --------------------------------------------------------------------------- #
def discover_jobs(db: Session, max_jobs: int = 30) -> Dict[str, Any]:
    """Search LinkedIn for the target roles and store postings as `new`.

    Reuses the authenticated persistent session. Jobs are scored later by the
    batch scorer; nothing is applied to.
    """
    setup_automation_logging()
    from playwright.sync_api import sync_playwright

    roles = config.target_roles()
    locations = config.target_locations() or [""]
    summary: Dict[str, Any] = {"discovered": 0, "new": 0}

    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False)
        page = context.new_page()
        try:
            if not _is_logged_in(page):
                raise LinkedInAuthError(
                    "Not logged in to LinkedIn. Run `python -m automation.linkedin_apply --login` "
                    "and sign in once; the session will persist."
                )
            for role in roles:
                if summary["discovered"] >= max_jobs:
                    break
                for location in locations:
                    if summary["discovered"] >= max_jobs:
                        break
                    for url in _collect_job_urls(page, role, location, limit=10):
                        if summary["discovered"] >= max_jobs:
                            break
                        data = _read_job(page, url)
                        if not data:
                            continue
                        summary["discovered"] += 1
                        _, created = crud.upsert_job(db, source=JobSource.LINKEDIN, **data)
                        if created:
                            summary["new"] += 1
                        db.commit()
                        human_delay(1.5, 3.5)
        finally:
            context.close()
    logger.info("LinkedIn discovery complete: %s", summary)
    return summary


# --------------------------------------------------------------------------- #
# Run (LEGACY auto-apply — no longer wired into the scheduler)                 #
# --------------------------------------------------------------------------- #
def run_linkedin_easy_apply(
    db: Session,
    max_per_run: Optional[int] = None,
    dry_run: Optional[bool] = None,
) -> Dict[str, Any]:
    setup_automation_logging()
    from playwright.sync_api import sync_playwright

    base_resume_data = config.load_base_resume_data()
    applicant = applicant_from_resume(base_resume_data)
    cap = max_per_run or config.MAX_APPLICATIONS_PER_RUN
    dry_run = config.AUTOMATION_DRY_RUN if dry_run is None else dry_run
    roles = config.target_roles()
    locations = config.target_locations() or [""]
    threshold = crud.get_setting(db, "score_threshold", config.keywords_defaults()["score_threshold"])

    summary = {"discovered": 0, "scored": 0, "submitted": 0, "needs_review": 0,
               "failed": 0, "dry_run": dry_run, "cap": cap}

    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False)
        page = context.new_page()
        try:
            if not _is_logged_in(page):
                raise LinkedInAuthError(
                    "Not logged in to LinkedIn. Run `python -m automation.linkedin_apply --login` "
                    "and sign in once; the session will persist."
                )
            for role in roles:
                if summary["submitted"] >= cap or "llm_error" in summary:
                    break
                for location in locations:
                    if summary["submitted"] >= cap or "llm_error" in summary:
                        break
                    urls = _collect_job_urls(page, role, location, limit=cap * 3)
                    for url in urls:
                        if summary["submitted"] >= cap or "llm_error" in summary:
                            break
                        data = _read_job(page, url)
                        if not data:
                            continue
                        summary["discovered"] += 1
                        job, _ = crud.upsert_job(db, source=JobSource.LINKEDIN, **data)
                        db.commit()

                        # Score in-session (needs the description we just read).
                        try:
                            result = score_and_store(db, job, base_resume_data=base_resume_data, threshold=threshold)
                            summary["scored"] += 1
                        except LLMError as exc:
                            logger.error(
                                "LLM unavailable while scoring LinkedIn job %s: %s — "
                                "stopping this run; unscored jobs retry next cycle.",
                                job.id,
                                exc,
                            )
                            summary["llm_error"] = str(exc)
                            break
                        except Exception:
                            logger.exception("Scoring failed for LinkedIn job %s", job.id)
                            continue
                        if result["status"] != JobStatus.QUEUED:
                            continue

                        # Ensure a resume PDF (Easy Apply can proceed without one,
                        # but we prefer to attach the tailored version).
                        resume_path = None
                        rv = crud.latest_resume_version(db, job.id)
                        if rv and rv.pdf_path and os.path.exists(rv.pdf_path):
                            resume_path = rv.pdf_path
                        else:
                            try:
                                rv = tailor_and_store(db, job, base_resume_data)
                                resume_path = rv.pdf_path if rv and rv.pdf_path and os.path.exists(rv.pdf_path) else None
                            except Exception:
                                logger.exception("Resume gen failed for job %s", job.id)

                        try:
                            status, notes, answers = easy_apply_flow(
                                page, job, resume_path, base_resume_data, applicant, dry_run
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Easy Apply failed for job %s", job.id)
                            status, notes, answers = ApplicationStatus.FAILED, f"Exception: {exc}", {}

                        crud.create_application(
                            db, job_id=job.id, resume_version_id=(rv.id if rv else None),
                            status=status, platform_response_notes=notes, custom_answers=answers or None,
                        )
                        if status == ApplicationStatus.SUBMITTED:
                            crud.set_job_status(db, job, JobStatus.APPLIED)
                            summary["submitted"] += 1
                        elif status == ApplicationStatus.FAILED:
                            crud.set_job_status(db, job, JobStatus.FAILED)
                            summary["failed"] += 1
                        else:
                            crud.set_job_status(db, job, JobStatus.NEEDS_REVIEW)
                            summary["needs_review"] += 1
                        db.commit()
                        long_delay()  # 3-8s spacing between applications
        finally:
            context.close()

    logger.info("LinkedIn Easy Apply run complete: %s", summary)
    return summary


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--login" in sys.argv:
        open_for_manual_login()
    else:
        from backend.db.session import SessionLocal, init_db

        init_db()
        _db = SessionLocal()
        try:
            print(run_linkedin_easy_apply(_db))
        finally:
            _db.close()
