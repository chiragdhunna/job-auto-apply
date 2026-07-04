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


def score_new() -> Dict[str, Any]:
    return _req("POST", "/jobs/score")


def score_job(job_id: int) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/score")


def tailor_resume(job_id: int) -> Dict[str, Any]:
    return _req("POST", f"/jobs/{job_id}/resume")


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
