"""Web-wide job board scrapers — free public JSON APIs, no browser, no keys.

Sources (all keyless):
  Remotive   https://remotive.com/api/remote-jobs?search={kw}     (remote jobs)
  RemoteOK   https://remoteok.com/api                              (remote jobs)
  Arbeitnow  https://www.arbeitnow.com/api/job-board-api           (EU-heavy, visa flag)
  The Muse   https://www.themuse.com/api/public/jobs               (worldwide)

Optional (free tier, needs keys in .env):
  Adzuna     https://api.adzuna.com/v1/api/jobs/{cc}/search/1      (UK/India/... aggregator)

Jobs matching the configured target_roles keywords (and, softly, the target
locations) are stored with status `new` for the scorer to rank. The scorer is
the precision layer — these scrapers favour recall.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import requests
from sqlalchemy.orm import Session

from backend import config
from backend.scrapers.base import (
    BaseScraper,
    ScrapedJob,
    persist_scraped_jobs,
    role_keywords,
    strip_html,
    title_matches_roles,
)

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
    """Web boards: strict title keywords OR (engineer-type title + tech tags).

    Boards like Remotive/RemoteOK match search terms against full descriptions,
    so their result sets are noisy; and good roles ("Senior AI Engineer") don't
    always contain the exact target keywords. The LLM scorer is the precision
    layer — this just keeps obvious non-engineering noise out.
    """
    if title_matches_roles(title, roles):
        return True
    t = (title or "").lower()
    if not any(w in t for w in ROLE_WORDS):
        return False
    tagset = {str(x).lower().strip() for x in (tags or [])}
    return bool(tagset & TECH_TAGS)


def location_ok(loc_text: Optional[str], targets: Sequence[str]) -> bool:
    """Soft location filter — err on the side of keeping (scorer decides)."""
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


def _get_json(url: str, params: Optional[Dict[str, Any]] = None):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
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


class _WebScraper(BaseScraper):
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


class RemotiveScraper(_WebScraper):
    source = "remotive"
    URL = "https://remotive.com/api/remote-jobs"

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        # Query per distinctive keyword — Remotive's search is fuzzy and matches
        # descriptions, so results are filtered hard below.
        for term in (role_keywords(self.roles) or [""])[:6]:
            data = _get_json(self.URL, {"search": term, "limit": 50})
            for j in (data or {}).get("jobs", []) or []:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                category = (j.get("category") or "").lower()
                if category and "software" not in category and "data" not in category:
                    continue  # writers/marketing/etc. matched on description text
                title = j.get("title") or ""
                company = j.get("company_name") or "Unknown"
                location = j.get("candidate_required_location")
                if not looks_relevant(title, j.get("tags"), self.roles):
                    continue
                if company.lower() in self.exclude or not location_ok(location, self.locations):
                    continue
                out.append(ScrapedJob(
                    source=self.source, external_id=jid, title=title, company=company,
                    url=j.get("url") or "", location=location,
                    description_raw=strip_html(j.get("description")),
                    salary_range=(j.get("salary") or None),
                ))
        logger.info("[remotive] %d matching jobs", len(out))
        return out


class RemoteOKScraper(_WebScraper):
    source = "remoteok"
    URL = "https://remoteok.com/api"

    def scrape(self) -> List[ScrapedJob]:
        data = _get_json(self.URL)
        out: List[ScrapedJob] = []
        if not isinstance(data, list):
            return out
        for j in data:
            if not isinstance(j, dict) or "position" not in j:
                continue  # first element is a legal notice
            title = j.get("position") or ""
            company = j.get("company") or "Unknown"
            location = j.get("location")
            if not looks_relevant(title, j.get("tags"), self.roles):
                continue
            if company.lower() in self.exclude or not location_ok(location, self.locations):
                continue
            salary = None
            smin, smax = j.get("salary_min") or 0, j.get("salary_max") or 0
            if smax:
                salary = f"${int(smin):,} - ${int(smax):,}" if smin else f"up to ${int(smax):,}"
            out.append(ScrapedJob(
                source=self.source, external_id=str(j.get("id")), title=title,
                company=company, url=j.get("url") or j.get("apply_url") or "",
                location=location or "Remote",
                description_raw=strip_html(j.get("description")), salary_range=salary,
            ))
        logger.info("[remoteok] %d matching jobs", len(out))
        return out


class ArbeitnowScraper(_WebScraper):
    source = "arbeitnow"
    URL = "https://www.arbeitnow.com/api/job-board-api"
    MAX_PAGES = 3

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        url: Optional[str] = self.URL
        for _ in range(self.MAX_PAGES):
            if not url:
                break
            data = _get_json(url)
            if not data:
                break
            for j in data.get("data", []) or []:
                title = j.get("title") or ""
                company = j.get("company_name") or "Unknown"
                if not looks_relevant(title, j.get("tags"), self.roles):
                    continue
                if company.lower() in self.exclude:
                    continue
                location = j.get("location")
                visa = bool(j.get("visa_sponsorship"))
                remote = bool(j.get("remote"))
                loc_display = f"{location} (Remote)" if remote and location else (location or ("Remote" if remote else None))
                # Visa-sponsored roles bypass the location filter — that's the goal.
                if not visa and not location_ok(loc_display, self.locations):
                    continue
                desc = strip_html(j.get("description")) or ""
                if visa:
                    desc = "[This posting offers VISA SPONSORSHIP]\n\n" + desc
                out.append(ScrapedJob(
                    source=self.source, external_id=j.get("slug"), title=title,
                    company=company, url=j.get("url") or "", location=loc_display,
                    description_raw=desc,
                ))
            url = ((data.get("links") or {}).get("next"))
        logger.info("[arbeitnow] %d matching jobs", len(out))
        return out


class TheMuseScraper(_WebScraper):
    source = "themuse"
    URL = "https://www.themuse.com/api/public/jobs"
    PAGES = 3
    CATEGORIES = ("Software Engineering", "Data and Analytics")

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        for category in self.CATEGORIES:
            for page in range(1, self.PAGES + 1):
                data = _get_json(self.URL, {"category": category, "page": page})
                for j in (data or {}).get("results", []) or []:
                    jid = str(j.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    title = j.get("name") or ""
                    company = (j.get("company") or {}).get("name") or "Unknown"
                    locs = [l.get("name", "") for l in (j.get("locations") or [])]
                    location = "; ".join(x for x in locs if x) or None
                    # Category is already tech — accept engineer-type titles too.
                    t = title.lower()
                    if not (title_matches_roles(title, self.roles)
                            or any(w in t for w in ROLE_WORDS)):
                        continue
                    if company.lower() in self.exclude or not location_ok(location, self.locations):
                        continue
                    out.append(ScrapedJob(
                        source=self.source, external_id=jid, title=title, company=company,
                        url=((j.get("refs") or {}).get("landing_page")) or "",
                        location=location, description_raw=strip_html(j.get("contents")),
                    ))
        logger.info("[themuse] %d matching jobs", len(out))
        return out


class AdzunaScraper(_WebScraper):
    """Optional aggregator with strong UK/India coverage. Free tier, needs keys.

    Set ADZUNA_APP_ID / ADZUNA_APP_KEY in .env (https://developer.adzuna.com).
    """

    source = "adzuna"
    URL = "https://api.adzuna.com/v1/api/jobs/{cc}/search/1"
    COUNTRY_FOR_TARGET = {"united kingdom": "gb", "india": "in", "remote": "gb"}

    def _countries(self) -> List[str]:
        ccs: List[str] = []
        for t in (self.locations or ["united kingdom"]):
            cc = self.COUNTRY_FOR_TARGET.get(t.lower().strip())
            if cc and cc not in ccs:
                ccs.append(cc)
        return ccs or ["gb"]

    def scrape(self) -> List[ScrapedJob]:
        if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
            return []
        out: List[ScrapedJob] = []
        seen = set()
        for cc in self._countries():
            for role in (self.roles or [""]):
                data = _get_json(self.URL.format(cc=cc), {
                    "app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
                    "what": role, "results_per_page": 25,
                })
                for j in (data or {}).get("results", []) or []:
                    jid = str(j.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    title = j.get("title") or ""
                    company = (j.get("company") or {}).get("display_name") or "Unknown"
                    if not title_matches_roles(title, self.roles):
                        continue
                    if company.lower() in self.exclude:
                        continue
                    salary = None
                    smin, smax = j.get("salary_min"), j.get("salary_max")
                    if smax:
                        salary = f"{int(smin or 0):,} - {int(smax):,}"
                    out.append(ScrapedJob(
                        source=self.source, external_id=jid, title=title, company=company,
                        url=j.get("redirect_url") or "",
                        location=(j.get("location") or {}).get("display_name"),
                        description_raw=j.get("description"), salary_range=salary,
                    ))
        logger.info("[adzuna] %d matching jobs", len(out))
        return out


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def run_web_scrape(db: Session, platform_toggles: Optional[Dict[str, bool]] = None) -> Dict[str, Dict]:
    """Scrape all web-wide boards (gated by the `web_boards` platform toggle)."""
    if platform_toggles is not None and not platform_toggles.get("web_boards", True):
        return {"web_boards": {"skipped": "platform disabled"}}

    roles = config.target_roles()
    locations = config.target_locations()
    exclude = config.exclude_companies()

    scrapers: List[BaseScraper] = [
        RemotiveScraper(roles, locations, exclude),
        RemoteOKScraper(roles, locations, exclude),
        ArbeitnowScraper(roles, locations, exclude),
        TheMuseScraper(roles, locations, exclude),
        AdzunaScraper(roles, locations, exclude),
    ]
    summary: Dict[str, Dict] = {}
    for scraper in scrapers:
        try:
            jobs = scraper.scrape()
        except Exception as exc:  # noqa: BLE001 — one source must not break the run
            logger.exception("[%s] scrape failed", scraper.source)
            summary[scraper.source] = {"error": str(exc)}
            continue
        created, seen = persist_scraped_jobs(db, jobs)
        summary[scraper.source] = {"found": seen, "new": created}
    return summary
