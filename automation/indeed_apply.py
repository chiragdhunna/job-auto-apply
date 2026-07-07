"""Automated Indeed application submission.

Mirrors the LinkedIn module's approach, adapted to Indeed:
  * Reuse a manually-authenticated persistent session (log in once; we never
    automate the Indeed login form).
  * Discover jobs by searching the target roles, read each posting, score it,
    and run the Indeed Apply ("Apply now") flow for jobs above threshold.
  * "Apply on company site" postings are left for manual review (handled by the
    ATS applier when they point at Greenhouse/Lever).

Indeed is aggressive about bot detection, so this uses the same stealth helpers
plus long randomised delays and a hard per-run cap. Selectors will need periodic
maintenance — every action is logged to logs/automation.log.

Set the Indeed domain for your region via INDEED_DOMAIN (e.g. https://uk.indeed.com
or https://in.indeed.com); defaults to https://www.indeed.com.
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

logger = logging.getLogger("jobctl.automation.indeed")

INDEED_DOMAIN = (os.getenv("INDEED_DOMAIN") or "https://www.indeed.com").rstrip("/")
SEARCH_URL = INDEED_DOMAIN + "/jobs?q={kw}&l={loc}"
MAX_APPLY_STEPS = 12


class IndeedAuthError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Session                                                                      #
# --------------------------------------------------------------------------- #
def _is_logged_in(page) -> bool:
    page.goto(INDEED_DOMAIN + "/", wait_until="domcontentloaded", timeout=45000)
    human_delay(2.0, 4.0)
    url = page.url.lower()
    if "account/login" in url or "auth" in url:
        return False
    # Presence of a "Sign in" link is a decent proxy for logged-out.
    if first_locator(page, ['a[href*="account/login"]', 'a:has-text("Sign in")']):
        return False
    return True


def open_for_manual_login() -> None:
    setup_automation_logging()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = launch_persistent_context(p, headless=False)
        page = context.new_page()
        page.goto(INDEED_DOMAIN + "/account/login", wait_until="domcontentloaded")
        wait_for_manual_login(context, "Indeed")
        try:
            context.close()
        except Exception:
            pass  # user already closed the window — session is saved


# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #
def _collect_job_urls(page, role: str, location: str, limit: int) -> List[str]:
    url = SEARCH_URL.format(kw=urllib.parse.quote(role), loc=urllib.parse.quote(location))
    logger.info("Indeed search: %s @ %s", role, location)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    human_delay(2.5, 5.0)
    hrefs: List[str] = []
    try:
        anchors = page.locator('a.jcs-JobTitle, h2.jobTitle a, a[data-jk], a[id^="job_"]')
        count = min(anchors.count(), limit)
        for i in range(count):
            a = anchors.nth(i)
            jk = a.get_attribute("data-jk")
            href = a.get_attribute("href")
            if jk:
                hrefs.append(f"{INDEED_DOMAIN}/viewjob?jk={jk}")
            elif href:
                hrefs.append(href if href.startswith("http") else INDEED_DOMAIN + href)
    except Exception:
        logger.debug("Could not enumerate Indeed cards", exc_info=True)
    seen = set()
    return [h for h in hrefs if not (h.split("&")[0] in seen or seen.add(h.split("&")[0]))]


def _text(page, selectors: List[str]) -> Optional[str]:
    loc = first_locator(page, selectors)
    if loc:
        try:
            return (loc.inner_text() or "").strip()
        except Exception:
            return None
    return None


def _read_job(page, url: str) -> Optional[Dict[str, Any]]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_delay(2.0, 4.0)
        title = _text(page, [".jobsearch-JobInfoHeader-title", 'h1[data-testid="jobsearch-JobInfoHeader-title"]', "h1"])
        company = _text(page, ['[data-company-name="true"]', '[data-testid="inlineHeader-companyName"]', ".jobsearch-CompanyInfoContainer a"])
        location = _text(page, ['[data-testid="job-location"]', ".jobsearch-JobInfoHeader-subtitle div"])
        description = _text(page, ["#jobDescriptionText", ".jobsearch-jobDescriptionText"])
        external_id = None
        if "jk=" in url:
            external_id = url.split("jk=")[-1].split("&")[0]
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
        logger.debug("Failed to read Indeed job at %s", url, exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# Apply flow                                                                   #
# --------------------------------------------------------------------------- #
def _apply_root(page):
    """Indeed Apply may render inside an iframe; return a frame_locator-ish root."""
    for sel in ['iframe[title*="Apply"]', 'iframe[id*="indeedapply"]', 'iframe[src*="smartapply"]']:
        try:
            fl = page.frame_locator(sel)
            if fl.locator("button, input, textarea").count() > 0:
                return fl
        except Exception:
            continue
    return page


def _fill_visible_step(root, page, job, base_resume_data, resume_path, applicant) -> Dict[str, str]:
    filled: Dict[str, str] = {}
    try:
        fi = root.locator('input[type="file"]').first
        if fi.count() > 0 and resume_path:
            fi.set_input_files(resume_path)
            short_delay()
    except Exception:
        pass
    try:
        inputs = root.locator('input[type="text"], input[type="tel"], input[type="email"]')
        for i in range(inputs.count()):
            el = inputs.nth(i)
            try:
                if not el.is_visible() or (el.input_value() or "").strip():
                    continue
            except Exception:
                continue
            label = (el.get_attribute("aria-label") or el.get_attribute("name") or "").lower()
            if "phone" in label or "mobile" in label:
                type_phone(el, applicant.get("phone", ""))
            elif "email" in label:
                human_type(el, applicant.get("email", ""))
            elif "name" in label and applicant.get("full_name"):
                human_type(el, applicant["full_name"])
    except Exception:
        logger.debug("indeed input fill issue", exc_info=True)
    try:
        textareas = root.locator("textarea")
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
        logger.debug("indeed textarea fill issue", exc_info=True)
    return filled


def indeed_apply_flow(page, job, resume_path, base_resume_data, applicant, dry_run) -> Tuple[str, str, Dict[str, str]]:
    # External applications aren't Indeed Apply.
    if first_locator(page, ['span:has-text("Apply on company site")', 'a:has-text("Apply on company site")']):
        return ApplicationStatus.PENDING_REVIEW, "External 'Apply on company site' — handle via ATS/manual", {}

    btn = first_locator(page, [
        "#indeedApplyButton",
        ".indeed-apply-button",
        'button:has-text("Apply now")',
        'span:has-text("Apply now")',
    ])
    if not btn:
        return ApplicationStatus.PENDING_REVIEW, "No Indeed Apply button found", {}
    human_click(btn)
    human_delay(2.0, 4.0)

    answers: Dict[str, str] = {}
    for _ in range(MAX_APPLY_STEPS):
        root = _apply_root(page)
        answers.update(_fill_visible_step(root, page, job, base_resume_data, resume_path, applicant))
        human_delay(1.0, 2.5)

        submit = first_locator(page, [
            'button:has-text("Submit application")',
            'button:has-text("Submit your application")',
            'button[data-testid="submit-application"]',
        ])
        if submit:
            if dry_run:
                return ApplicationStatus.PENDING_REVIEW, "DRY RUN — reached submit, not clicked", answers
            human_click(submit)
            human_delay(2.0, 4.0)
            return ApplicationStatus.SUBMITTED, "Submitted via Indeed Apply", answers

        cont = first_locator(page, [
            'button:has-text("Continue")',
            'button[data-testid="continue-button"]',
            'button:has-text("Next")',
        ])
        if not cont:
            break
        human_click(cont)
        human_delay(1.5, 3.5)

    return ApplicationStatus.PENDING_REVIEW, "Could not complete Indeed Apply steps automatically", answers


# --------------------------------------------------------------------------- #
# Discovery only (no applying) — used by the recommendation pipeline           #
# --------------------------------------------------------------------------- #
def discover_jobs(db: Session, max_jobs: int = 30) -> Dict[str, Any]:
    """Search Indeed for the target roles and store postings as `new`."""
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
                raise IndeedAuthError(
                    "Not logged in to Indeed. Run `python -m automation.indeed_apply --login` "
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
                        _, created = crud.upsert_job(db, source=JobSource.INDEED, **data)
                        if created:
                            summary["new"] += 1
                        db.commit()
                        human_delay(1.5, 3.5)
        finally:
            context.close()
    logger.info("Indeed discovery complete: %s", summary)
    return summary


# --------------------------------------------------------------------------- #
# Run (LEGACY auto-apply — no longer wired into the scheduler)                 #
# --------------------------------------------------------------------------- #
def run_indeed_applications(
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
                raise IndeedAuthError(
                    "Not logged in to Indeed. Run `python -m automation.indeed_apply --login` "
                    "and sign in once; the session will persist."
                )
            for role in roles:
                if summary["submitted"] >= cap or "llm_error" in summary:
                    break
                for location in locations:
                    if summary["submitted"] >= cap or "llm_error" in summary:
                        break
                    for url in _collect_job_urls(page, role, location, limit=cap * 3):
                        if summary["submitted"] >= cap or "llm_error" in summary:
                            break
                        data = _read_job(page, url)
                        if not data:
                            continue
                        summary["discovered"] += 1
                        job, _ = crud.upsert_job(db, source=JobSource.INDEED, **data)
                        db.commit()
                        try:
                            result = score_and_store(db, job, base_resume_data=base_resume_data, threshold=threshold)
                            summary["scored"] += 1
                        except LLMError as exc:
                            logger.error(
                                "LLM unavailable while scoring Indeed job %s: %s — "
                                "stopping this run; unscored jobs retry next cycle.",
                                job.id,
                                exc,
                            )
                            summary["llm_error"] = str(exc)
                            break
                        except Exception:
                            logger.exception("Scoring failed for Indeed job %s", job.id)
                            continue
                        if result["status"] != JobStatus.QUEUED:
                            continue

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
                            status, notes, answers = indeed_apply_flow(
                                page, job, resume_path, base_resume_data, applicant, dry_run
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Indeed apply failed for job %s", job.id)
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
                        long_delay()
        finally:
            context.close()

    logger.info("Indeed application run complete: %s", summary)
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
            print(run_indeed_applications(_db))
        finally:
            _db.close()
