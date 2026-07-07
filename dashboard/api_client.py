"""Thin HTTP client the Streamlit dashboard uses to talk to the FastAPI backend.

Keeping the dashboard API-driven (rather than importing the backend directly)
means the control/visibility surface is exactly the same API the scheduler and
any other client use.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 60


class APIError(RuntimeError):
    pass


def _req(method: str, path: str, **kwargs) -> Any:
    url = f"{BACKEND_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise APIError(f"Cannot reach backend at {BACKEND_URL}. Is it running? ({exc})") from exc
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except ValueError:
            pass
        raise APIError(f"{method} {path} -> {resp.status_code}: {detail}")
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    return resp.content


# -- health / llm ----------------------------------------------------------- #
def health() -> Dict[str, Any]:
    return _req("GET", "/health")


def llm_status() -> Dict[str, Any]:
    return _req("GET", "/settings/llm-status")


# -- settings --------------------------------------------------------------- #
def get_settings() -> Dict[str, Any]:
    return _req("GET", "/settings")


def update_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _req("PUT", "/settings", json=payload)


def clear_data(delete_resume_files: bool = True, include_settings: bool = False) -> Dict[str, Any]:
    return _req("POST", "/settings/clear-data", json={
        "delete_resume_files": delete_resume_files,
        "include_settings": include_settings,
        "confirm": "DELETE",
    })


# -- jobs ------------------------------------------------------------------- #
def list_jobs(status: Optional[str] = None, source: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    if source:
        params["source"] = source
    return _req("GET", "/jobs", params=params)


def get_job(job_id: int) -> Dict[str, Any]:
    return _req("GET", f"/jobs/{job_id}")


def set_job_status(job_id: int, status: str) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/status", json={"status": status})


def scrape_now() -> Dict[str, Any]:
    return _req("POST", "/jobs/scrape")


def get_recommended(
    min_score: Optional[float] = None,
    include_done: bool = False,
    source: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"include_done": include_done, "limit": limit}
    if min_score is not None:
        params["min_score"] = min_score
    if source:
        params["source"] = source
    return _req("GET", "/jobs/recommended", params=params)


def mark_applied(job_id: int, note: Optional[str] = None) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/mark-applied", json={"note": note} if note else {})


def unmark_applied(job_id: int) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/unmark-applied")


def score_new() -> Dict[str, Any]:
    return _req("POST", "/jobs/score")


def score_job(job_id: int) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/score")


def tailor_resume(job_id: int, force_tailor: bool = False) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/resume", params={"force_tailor": force_tailor})


def list_job_resumes(job_id: int) -> List[Dict[str, Any]]:
    return _req("GET", f"/jobs/{job_id}/resumes")


def get_resume_version(rv_id: int) -> Dict[str, Any]:
    return _req("GET", f"/jobs/resume-version/{rv_id}")


def resume_download_url(rv_id: int) -> str:
    return f"{BACKEND_URL}/jobs/resume-download/{rv_id}"


def resume_pdf_bytes(rv_id: int) -> bytes:
    return _req("GET", f"/jobs/resume-download/{rv_id}")


def generate_answers(job_id: int, questions: Optional[List[str]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if questions:
        body["questions"] = questions
    return _req("POST", f"/jobs/{job_id}/answers", json=body)


# -- applications ----------------------------------------------------------- #
def list_applications() -> List[Dict[str, Any]]:
    return _req("GET", "/applications")


# -- outreach (DRAFT-ONLY: nothing here sends anything) ---------------------- #
def outreach_overview() -> List[Dict[str, Any]]:
    return _req("GET", "/outreach")


def get_outreach(job_id: int) -> Dict[str, Any]:
    return _req("GET", f"/outreach/{job_id}")


def regenerate_outreach(job_id: int) -> Dict[str, Any]:
    return _req("POST", f"/outreach/{job_id}/regenerate")


def save_outreach_draft(job_id: int, draft_id: int, draft_text: str, subject: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"draft_text": draft_text}
    if subject is not None:
        body["subject"] = subject
    return _req("PUT", f"/outreach/{job_id}/draft/{draft_id}", json=body)


def mark_draft_sent(job_id: int, draft_id: int) -> Dict[str, Any]:
    return _req("PUT", f"/outreach/{job_id}/draft/{draft_id}/mark-sent")


def skip_draft(job_id: int, draft_id: int) -> Dict[str, Any]:
    return _req("PUT", f"/outreach/{job_id}/draft/{draft_id}/skip")


def set_outreach_contact(job_id: int, **fields) -> Dict[str, Any]:
    return _req("PUT", f"/outreach/{job_id}/contact", json=fields)
