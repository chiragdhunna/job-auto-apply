"""JD vs. resume fit scoring.

Routes through the shared LLM client (``backend.llm.client.generate``) — Gemini
primary, Ollama fallback — never a provider SDK directly. The model is asked for
strict JSON:

    {"score": 0-100, "reasoning": "...", "matched_skills": [...], "gaps": [...]}

Jobs are updated with fit_score + the full detail JSON; status becomes
``scored`` (or ``queued`` when the score meets the threshold).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend import config
from backend.db import crud
from backend.db.models import Job, JobStatus
from backend.llm.client import LLMError, generate

logger = logging.getLogger("job_auto_apply.scoring")

MAX_JD_CHARS = 6000  # keep prompts bounded (local models especially)


def build_scoring_prompt(job: Job, base_resume_data: Dict[str, Any]) -> str:
    resume_json = json.dumps(base_resume_data, ensure_ascii=False, indent=2)
    description = (job.description_raw or "").strip()
    if len(description) > MAX_JD_CHARS:
        description = description[:MAX_JD_CHARS] + "\n...[truncated]"
    return f"""You are an expert technical recruiter evaluating how well a candidate fits a role.

CANDIDATE PROFILE (JSON):
{resume_json}

JOB POSTING
Title: {job.title}
Company: {job.company}
Location: {job.location or "Not specified"}
Description:
\"\"\"
{description or "No description available."}
\"\"\"

Assess the fit considering: skills overlap, role and seniority alignment, domain
relevance, and location / work-authorization compatibility. Be calibrated:
reserve 85-100 for strong matches, 60-84 for plausible ones, and below 50 for
weak fits.

Return ONLY a JSON object with EXACTLY these keys and nothing else:
{{
  "score": <integer 0-100>,
  "reasoning": "<2-3 sentence justification>",
  "matched_skills": ["<skill the candidate has that the role wants>", ...],
  "gaps": ["<requirement the candidate is missing or light on>", ...]
}}"""


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object from a model response, tolerating markdown fences/prose."""
    if not text:
        raise ValueError("empty response")
    cleaned = text.strip()
    # Strip ```json ... ``` fences if present.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(100.0, score))

    def _as_list(v) -> List[str]:
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    return {
        "score": round(score, 1),
        "reasoning": str(data.get("reasoning", "")).strip(),
        "matched_skills": _as_list(data.get("matched_skills")),
        "gaps": _as_list(data.get("gaps")),
    }


def score_job(job: Job, base_resume_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score a single job. Raises LLMError on provider failure, ValueError on bad JSON."""
    if base_resume_data is None:
        base_resume_data = config.load_base_resume_data()
    prompt = build_scoring_prompt(job, base_resume_data)
    raw = generate(prompt, expect_json=True)
    return _normalize(_extract_json(raw))


def score_and_store(
    db: Session,
    job: Job,
    *,
    base_resume_data: Optional[Dict[str, Any]] = None,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    if threshold is None:
        threshold = crud.get_setting(
            db, "score_threshold", config.keywords_defaults()["score_threshold"]
        )
    result = score_job(job, base_resume_data)
    status = JobStatus.QUEUED if result["score"] >= float(threshold) else JobStatus.SCORED
    crud.set_job_score(db, job, score=result["score"], details=result, status=status)
    db.commit()
    logger.info(
        "Scored job %s '%s' -> %.1f (%s)", job.id, job.title[:50], result["score"], status
    )
    return {**result, "status": status, "job_id": job.id}


def score_new_jobs(db: Session, limit: Optional[int] = None) -> Dict[str, Any]:
    """Score every job with status 'new'. Returns a summary.

    On a provider outage the loop stops early (jobs stay 'new' and retry next
    cycle). On a per-job parse error the job is left 'new' and we continue.
    """
    base_resume_data = config.load_base_resume_data()
    threshold = crud.get_setting(
        db, "score_threshold", config.keywords_defaults()["score_threshold"]
    )
    jobs = crud.list_jobs(db, statuses=[JobStatus.NEW], limit=limit, order_desc=False)
    summary = {"scored": 0, "queued": 0, "failed": 0, "total": len(jobs)}
    for job in jobs:
        try:
            result = score_and_store(
                db, job, base_resume_data=base_resume_data, threshold=threshold
            )
        except LLMError as exc:
            logger.error("LLM unavailable while scoring job %s: %s. Stopping run.", job.id, exc)
            summary["failed"] += 1
            break
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Could not parse score for job %s: %s. Leaving as 'new'.", job.id, exc)
            summary["failed"] += 1
            continue
        summary["scored"] += 1
        if result["status"] == JobStatus.QUEUED:
            summary["queued"] += 1
    return summary
