"""LLM-based personalized outreach drafting. DRAFT-ONLY — never sends anything.

One LLM call per job produces both channel drafts (LinkedIn message + email)
as strict JSON. Quality is enforced in CODE, not just in the prompt:

  * a banned-phrase post-check catches template filler the model was told to
    avoid ("I hope this message finds you well", ...) — any hit flags the
    draft `needs_owner_input` instead of shipping cliché under the owner's name
  * the model self-reports `has_specific_hook`; false -> `needs_owner_input`
  * length guard trims runaway LinkedIn messages (~1000 char InMail ceiling)

Routes through the shared LLM client (Gemini primary, Ollama fallback).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from backend import config
from backend.llm.client import LLMError, generate
from backend.outreach.prompts import build_outreach_prompt

logger = logging.getLogger("job_auto_apply.outreach.drafts")

MAX_JD_CHARS = 5000
LINKEDIN_HARD_CAP = 1000  # InMail-style ceiling; prompt aims much shorter

# Post-check ban list (lowercase). Any hit => needs_owner_input.
BANNED_PHRASES = (
    "i hope this message finds you well",
    "i hope this email finds you well",
    "i hope you're doing well",
    "i hope you are doing well",
    "i am writing to express my interest",
    "i'm writing to express my interest",
    "i came across your job posting",
    "i recently came across",
    "dear sir or madam",
    "to whom it may concern",
    "i would be a great fit",
)


def _extract_json(raw: str) -> Dict[str, Any]:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def quality_flags(text: str) -> list:
    """Deterministic template-filler detector. Returns list of matched bans."""
    low = (text or "").lower()
    return [p for p in BANNED_PHRASES if p in low]


def _contact_line(contact: Optional[Dict[str, Any]]) -> str:
    if contact and contact.get("name"):
        title = f", {contact['title']}" if contact.get("title") else ""
        return f"{contact['name']}{title}"
    return "the Hiring Team (no individual contact was identified — keep the greeting role-generic)"


def draft_messages(
    job,
    contact: Optional[Dict[str, Any]] = None,
    applied_at: Optional[str] = None,
    base_resume_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate both drafts for a job. Returns:

    {"linkedin": {"text", "status"}, "email": {"subject", "text", "status"},
     "has_specific_hook": bool}

    status is "draft" or "needs_owner_input" (template filler detected / thin JD).
    Raises LLMError when the provider is down (caller decides how to surface).
    """
    if base_resume_data is None:
        base_resume_data = config.load_base_resume_data()

    jd = (job.description_raw or f"{job.title} at {job.company}").strip()
    if len(jd) > MAX_JD_CHARS:
        jd = jd[:MAX_JD_CHARS] + "\n...[truncated]"

    applied_line = ""
    if applied_at:
        applied_line = f"NOTE: the candidate already submitted an application on {applied_at}."

    prompt = build_outreach_prompt(
        job_title=job.title,
        company=job.company,
        job_description=jd,
        candidate_json=json.dumps(base_resume_data, ensure_ascii=False),
        contact_line=_contact_line(contact),
        applied_line=applied_line,
    )
    raw = generate(prompt, expect_json=True)
    data = _extract_json(raw)

    linkedin = str(data.get("linkedin_message") or "").strip()
    subject = str(data.get("email_subject") or "").strip()
    email_body = str(data.get("email_body") or "").strip()
    hook = bool(data.get("has_specific_hook", True))

    if len(linkedin) > LINKEDIN_HARD_CAP:
        linkedin = linkedin[:LINKEDIN_HARD_CAP - 1] + "…"

    def _status(text: str) -> str:
        flags = quality_flags(text)
        if flags:
            logger.warning("Draft for job %s tripped template-filler check: %s", job.id, flags)
            return "needs_owner_input"
        return "draft" if hook else "needs_owner_input"

    if not linkedin and not email_body:
        raise ValueError("model returned neither draft")

    return {
        "linkedin": {"text": linkedin, "status": _status(linkedin)},
        "email": {"subject": subject or f"{job.title} application — quick note",
                  "text": email_body, "status": _status(email_body)},
        "has_specific_hook": hook,
    }
