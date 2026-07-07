"""Shared helpers for the web-wide job board scrapers.

Extracted so each source can live in its own module (remoteok_scraper.py,
jobicy_scraper.py, ...) while sharing one HTTP helper, one relevance filter,
and one location filter. The per-source scrapers favour recall; the LLM scorer
is the precision layer downstream.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import requests

from backend.scrapers.base import BaseScraper, title_matches_roles

logger = logging.getLogger("job_auto_apply.scrapers.web")

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (job-auto-apply; personal job search)"}

# Location text that always passes when "Remote" is among the targets.
_REMOTE_WORDS = ("remote", "worldwide", "anywhere", "flexible", "global")
_LOCATION_ALIASES = {
    "united kingdom": ("united kingdom", "uk", "england", "london", "scotland", "wales"),
    "india": ("india",),
    "remote": _REMOTE_WORDS,
}

# Tags that mark a posting as technically relevant to the target stack.
TECH_TAGS = {
    "python", "backend", "flutter", "dart", "llm", "genai", "generative ai",
    "machine learning", "ml", "ai/ml", "fastapi", "django", "flask",
    "spring boot", "node", "node.js", "react", "api",
}
# A relaxed match still requires the title to look like an engineering role.
ROLE_WORDS = ("engineer", "developer", "architect", "programmer", "scientist", "swe", "sde")


def looks_relevant(title: str, tags, roles: Sequence[str]) -> bool:
    """Strict title keyword match OR (engineer-type title + a tech tag)."""
    if title_matches_roles(title, roles):
        return True
    t = (title or "").lower()
    if not any(w in t for w in ROLE_WORDS):
        return False
    tagset = {str(x).lower().strip() for x in (tags or [])}
    return bool(tagset & TECH_TAGS)


def location_ok(loc_text: Optional[str], targets: Sequence[str]) -> bool:
    """Soft location filter — err on the side of keeping (the scorer decides)."""
    if not targets:
        return True
    loc = (loc_text or "").lower().strip()
    if not loc:
        return True  # unknown location -> keep, let the scorer judge
    for target in targets:
        t = target.lower().strip()
        for alias in _LOCATION_ALIASES.get(t, (t,)):
            if alias in loc:
                return True
    return False


def get_json(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict] = None):
    """GET + parse JSON, returning None (with a warning) on any failure."""
    try:
        resp = requests.get(url, params=params, headers=headers or HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("[web] request failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        logger.warning("[web] HTTP %s for %s", resp.status_code, url)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("[web] non-JSON response from %s", url)
        return None


class WebScraper(BaseScraper):
    """Common ctor + keep() for web-board scrapers."""

    def __init__(self, roles: Sequence[str], locations: Sequence[str],
                 exclude: Optional[Sequence[str]] = None) -> None:
        self.roles = list(roles or [])
        self.locations = list(locations or [])
        self.exclude = {c.lower() for c in (exclude or [])}

    def _keep(self, title: str, company: str, location: Optional[str]) -> bool:
        if not title or not title_matches_roles(title, self.roles):
            return False
        if (company or "").lower() in self.exclude:
            return False
        return location_ok(location, self.locations)
