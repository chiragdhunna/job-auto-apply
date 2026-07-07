"""Identify the likely recruiter / hiring manager for a job. DRAFT-ONLY feature.

Strategies, in priority order:

1. **JD text extraction** — many postings name a recruiter or hiring manager
   outright. The LLM (shared client: Gemini primary, Ollama fallback) extracts
   any named contact as strict JSON. ANTI-FABRICATION GUARD: a returned name is
   only accepted if it literally appears in the JD text — an LLM inventing
   "Sarah Mitchell, Talent Partner" gets rejected deterministically, not by
   trusting the model's honesty.
   Deterministic extras: recruiting emails and linkedin.com/in/... URLs are
   pulled by regex (no LLM required, can't hallucinate).

2. **Company careers-page check** — best-effort fetch of the posting page for a
   named recruiting contact (same guard applies to its text).

3. **LinkedIn connector hook** — if the owner wires a people-search connector,
   `search_via_linkedin_connector` is the extension point. Deliberately NOT
   implemented via browser scraping of LinkedIn search results (ToS-adversarial,
   same category excluded elsewhere in this project). Absent connector -> skip.

If everything fails: return an honest not-found result (confidence "none").
NEVER a guessed or fabricated name. The message drafter then addresses the
"Hiring Team" generically instead.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import requests

from backend.llm.client import LLMError, generate

logger = logging.getLogger("job_auto_apply.outreach.contacts")

MAX_TEXT_CHARS = 6000

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?")

# Generic mailbox prefixes that are contact channels, not people.
_GENERIC_MAILBOX = ("careers", "jobs", "recruiting", "talent", "hr", "hiring", "apply")

_EXTRACT_PROMPT = """Read this job posting and determine whether it explicitly names a specific
recruiter, talent partner, or hiring manager AS A PERSON (a real first/last
name written in the text — job titles alone do not count, team names do not
count).

Rules:
- Only report a name that is LITERALLY WRITTEN in the text below.
- If no individual person is named, return found=false. Do NOT guess or invent.

Return ONLY this JSON, nothing else:
{"found": true/false, "name": "<exact name as written or null>",
 "title": "<their title if stated, else null>", "confidence": "high|medium|low"}

JOB POSTING TEXT:
\"\"\"
{text}
\"\"\""""


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


def _name_appears_in_text(name: str, text: str) -> bool:
    """Anti-fabrication check: every word of the name must appear in the text."""
    if not name or not text:
        return False
    low = text.lower()
    words = [w for w in re.split(r"\s+", name.strip()) if len(w) > 1]
    if not words:
        return False
    return all(w.lower() in low for w in words)


def _regex_contacts(text: str) -> Dict[str, Optional[str]]:
    """Deterministic extraction: emails + LinkedIn profile URLs (can't hallucinate)."""
    email = None
    personal_email = None
    for m in _EMAIL_RE.findall(text or ""):
        prefix = m.split("@")[0].lower()
        if any(g in prefix for g in _GENERIC_MAILBOX):
            email = email or m  # generic recruiting inbox — still useful
        else:
            personal_email = personal_email or m
    linkedin = None
    lm = _LINKEDIN_RE.search(text or "")
    if lm:
        linkedin = lm.group(0)
    return {"email": personal_email or email, "linkedin_url": linkedin}


def _llm_extract_person(text: str) -> Optional[Dict[str, Any]]:
    """LLM pass over text; returns validated {name,title,confidence} or None."""
    snippet = (text or "").strip()[:MAX_TEXT_CHARS]
    if not snippet:
        return None
    try:
        raw = generate(_EXTRACT_PROMPT.replace("{text}", snippet), expect_json=True)
        data = _extract_json(raw)
    except LLMError:
        raise  # provider down — caller decides (scheduler bails, API 503s)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Contact extraction returned unparseable JSON — treating as not found.")
        return None
    if not data.get("found"):
        return None
    name = (data.get("name") or "").strip()
    if not name or not _name_appears_in_text(name, snippet):
        logger.warning(
            "LLM returned a contact name (%r) not present in the source text — "
            "rejecting as fabrication.", name[:40],
        )
        return None
    confidence = data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "medium"
    return {"name": name, "title": (data.get("title") or None), "confidence": confidence}


def _fetch_page_text(url: str) -> str:
    """Best-effort fetch of the posting/careers page for a secondary pass."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (job-auto-apply)"})
        if resp.status_code != 200:
            return ""
        from backend.scrapers.base import strip_html
        return (strip_html(resp.text) or "")[:MAX_TEXT_CHARS]
    except requests.RequestException:
        return ""


def search_via_linkedin_connector(company: str, role_hint: str = "Technical Recruiter") -> Optional[Dict[str, Any]]:
    """Optional extension point for a LinkedIn people-search connector/MCP tool.

    Deliberately unimplemented by default: this project does NOT scrape LinkedIn
    search results (ToS-adversarial). If the owner has a sanctioned connector,
    wire it here to return {"name","title","linkedin_url","confidence"}.
    """
    logger.debug("No LinkedIn connector configured — skipping people search for %s.", company)
    return None


def find_contact(job) -> Dict[str, Any]:
    """Identify the best-available contact for a job. Never fabricates.

    Returns a dict shaped for the outreach_contacts table:
      {name, title, linkedin_url, email, source, confidence}
    `confidence: "none"` + source "not_found" when nothing legitimate was found.
    """
    jd_text = job.description_raw or ""
    regexed = _regex_contacts(jd_text)

    # 1) Named person in the JD itself.
    person = _llm_extract_person(jd_text)
    if person:
        return {**person, **regexed, "source": "jd_text"}

    # 2) Posting/careers page (secondary text, same anti-fabrication guard).
    page_text = _fetch_page_text(job.url)
    if page_text and page_text[:500] != jd_text[:500]:
        page_regex = _regex_contacts(page_text)
        person = _llm_extract_person(page_text)
        if person:
            return {**person, "email": page_regex["email"] or regexed["email"],
                    "linkedin_url": page_regex["linkedin_url"] or regexed["linkedin_url"],
                    "source": "company_page"}
        regexed = {"email": regexed["email"] or page_regex["email"],
                   "linkedin_url": regexed["linkedin_url"] or page_regex["linkedin_url"]}

    # 3) Optional connector (no-op unless the owner wires one).
    connector = search_via_linkedin_connector(job.company)
    if connector:
        return {**connector, "email": regexed["email"], "source": "linkedin_connector"}

    # Honest not-found — possibly still carrying a recruiting inbox from regex.
    return {
        "name": None, "title": None,
        "linkedin_url": regexed["linkedin_url"], "email": regexed["email"],
        "source": "not_found", "confidence": "none",
    }
