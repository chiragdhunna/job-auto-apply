"""ATS public-API scrapers (lowest detection risk).

Public JSON endpoints used:
  Greenhouse : https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true
  Lever      : https://api.lever.co/v0/postings/{company}?mode=json
  Ashby      : https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
  Workday    : POST {tenant CxS}/jobs  (tenant-specific; best-effort, opt-in)

Company lists come from config/keywords.yaml -> `ats_companies`. Only titles
matching the configured target_roles are kept.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

import requests
from sqlalchemy.orm import Session

from backend import config
from backend.db.models import JobSource
from backend.scrapers.base import (
    BaseScraper,
    ScrapedJob,
    persist_scraped_jobs,
    strip_html,
    title_matches_roles,
)

logger = logging.getLogger("job_auto_apply.scrapers.ats")

DEFAULT_TIMEOUT = 20
HEADERS = {"User-Agent": "job-auto-apply/0.1 (personal job search; +local)"}


def _slug_to_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


class _CompanyListScraper(BaseScraper):
    """Common machinery for the per-company public-board scrapers."""

    def __init__(
        self,
        companies: Sequence[str],
        roles: Sequence[str],
        exclude: Optional[Sequence[str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.companies = list(companies or [])
        self.roles = list(roles or [])
        self.exclude = {c.lower() for c in (exclude or [])}
        self.timeout = timeout

    def _get_json(self, url: str):
        resp = requests.get(url, headers=HEADERS, timeout=self.timeout)
        if resp.status_code == 404:
            logger.warning("[%s] 404 for %s (bad company slug?)", self.source, url)
            return None
        if resp.status_code != 200:
            logger.warning("[%s] HTTP %s for %s", self.source, resp.status_code, url)
            return None
        try:
            return resp.json()
        except ValueError:
            logger.warning("[%s] non-JSON response from %s", self.source, url)
            return None

    def _scrape_company(self, slug: str) -> List[ScrapedJob]:  # pragma: no cover
        raise NotImplementedError

    def _excluded(self, company: str) -> bool:
        return company.lower() in self.exclude

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        for slug in self.companies:
            try:
                found = self._scrape_company(slug)
            except requests.RequestException as exc:
                logger.warning("[%s] request error for '%s': %s", self.source, slug, exc)
                continue
            logger.info("[%s] %s -> %d matching roles", self.source, slug, len(found))
            out.extend(found)
        return out


class GreenhouseScraper(_CompanyListScraper):
    source = JobSource.GREENHOUSE
    URL = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

    def _scrape_company(self, slug: str) -> List[ScrapedJob]:
        data = self._get_json(self.URL.format(company=slug))
        if not data:
            return []
        out: List[ScrapedJob] = []
        for j in data.get("jobs", []) or []:
            title = j.get("title") or ""
            if not title_matches_roles(title, self.roles):
                continue
            company = j.get("company_name") or _slug_to_name(slug)
            if self._excluded(company):
                continue
            location = (j.get("location") or {}).get("name")
            out.append(
                ScrapedJob(
                    source=self.source,
                    external_id=str(j.get("id")) if j.get("id") is not None else None,
                    title=title,
                    company=company,
                    url=j.get("absolute_url") or "",
                    location=location,
                    description_raw=strip_html(j.get("content")),
                )
            )
        return out


class LeverScraper(_CompanyListScraper):
    source = JobSource.LEVER
    URL = "https://api.lever.co/v0/postings/{company}?mode=json"

    def _scrape_company(self, slug: str) -> List[ScrapedJob]:
        data = self._get_json(self.URL.format(company=slug))
        if not data:
            return []
        company = _slug_to_name(slug)
        if self._excluded(company):
            return []
        out: List[ScrapedJob] = []
        for j in data:  # Lever returns a bare list
            title = j.get("text") or ""
            if not title_matches_roles(title, self.roles):
                continue
            cats = j.get("categories") or {}
            location = cats.get("location") or (cats.get("allLocations") or [None])[0]
            description = j.get("descriptionPlain") or j.get("descriptionBodyPlain")
            out.append(
                ScrapedJob(
                    source=self.source,
                    external_id=str(j.get("id")) if j.get("id") else None,
                    title=title,
                    company=company,
                    url=j.get("hostedUrl") or j.get("applyUrl") or "",
                    location=location,
                    description_raw=description,
                )
            )
        return out


class AshbyScraper(_CompanyListScraper):
    source = JobSource.ASHBY
    URL = "https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true"

    def _scrape_company(self, slug: str) -> List[ScrapedJob]:
        data = self._get_json(self.URL.format(company=slug))
        if not data:
            return []
        company = _slug_to_name(slug)
        if self._excluded(company):
            return []
        out: List[ScrapedJob] = []
        for j in data.get("jobs", []) or []:
            if j.get("isListed") is False:
                continue
            title = j.get("title") or ""
            if not title_matches_roles(title, self.roles):
                continue
            location = j.get("location")
            if j.get("isRemote") and location and "remote" not in location.lower():
                location = f"{location} (Remote)"
            out.append(
                ScrapedJob(
                    source=self.source,
                    external_id=str(j.get("id")) if j.get("id") else None,
                    title=title,
                    company=company,
                    url=j.get("jobUrl") or j.get("applyUrl") or "",
                    location=location,
                    description_raw=j.get("descriptionPlain"),
                    salary_range=_ashby_salary(j.get("compensation")),
                )
            )
        return out


class WorkdayScraper(BaseScraper):
    """Best-effort Workday scraper (opt-in).

    Workday has no single public API — each tenant exposes a CxS endpoint. Provide
    entries in keywords.yaml under `ats_companies.workday` as objects, e.g.::

        workday:
          - name: "Some Company"
            cxs_url: "https://company.wd1.myworkdayjobs.com/wday/cxs/company/External/jobs"
            site_url: "https://company.wd1.myworkdayjobs.com/en-US/External"

    If none are configured this scraper is a no-op.
    """

    source = JobSource.WORKDAY

    def __init__(self, entries, roles, exclude=None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.entries = list(entries or [])
        self.roles = list(roles or [])
        self.exclude = {c.lower() for c in (exclude or [])}
        self.timeout = timeout

    def _scrape_entry(self, entry: Dict) -> List[ScrapedJob]:
        cxs_url = entry.get("cxs_url")
        if not cxs_url:
            return []
        company = entry.get("name") or "Workday"
        if company.lower() in self.exclude:
            return []
        site_url = (entry.get("site_url") or "").rstrip("/")
        out: List[ScrapedJob] = []
        # Query once per role's raw text via searchText, de-duping by path.
        seen_paths = set()
        queries = self.roles or [""]
        for q in queries:
            body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q}
            resp = requests.post(cxs_url, json=body, headers=HEADERS, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning("[workday] HTTP %s for %s", resp.status_code, cxs_url)
                continue
            for jp in (resp.json() or {}).get("jobPostings", []) or []:
                title = jp.get("title") or ""
                path = jp.get("externalPath") or ""
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                if not title_matches_roles(title, self.roles):
                    continue
                out.append(
                    ScrapedJob(
                        source=self.source,
                        external_id=path or None,
                        title=title,
                        company=company,
                        url=f"{site_url}{path}" if site_url else path,
                        location=jp.get("locationsText"),
                    )
                )
        return out

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        for entry in self.entries:
            if not isinstance(entry, dict):
                logger.warning("[workday] skipping non-dict config entry: %r", entry)
                continue
            try:
                out.extend(self._scrape_entry(entry))
            except requests.RequestException as exc:
                logger.warning("[workday] request error: %s", exc)
        return out


def _ashby_salary(comp) -> Optional[str]:
    """Extract a human-readable salary summary from Ashby's compensation object."""
    if not isinstance(comp, dict):
        return None
    summary = comp.get("compensationTierSummary") or comp.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    tiers = comp.get("compensationTiers") or []
    if tiers and isinstance(tiers, list):
        title = tiers[0].get("title") if isinstance(tiers[0], dict) else None
        if title:
            return str(title)
    return None


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def build_scrapers(
    roles: Sequence[str],
    companies: Dict[str, list],
    exclude: Sequence[str],
) -> List[BaseScraper]:
    scrapers: List[BaseScraper] = []
    if companies.get("greenhouse"):
        scrapers.append(GreenhouseScraper(companies["greenhouse"], roles, exclude))
    if companies.get("lever"):
        scrapers.append(LeverScraper(companies["lever"], roles, exclude))
    if companies.get("ashby"):
        scrapers.append(AshbyScraper(companies["ashby"], roles, exclude))
    if companies.get("workday"):
        scrapers.append(WorkdayScraper(companies["workday"], roles, exclude))
    return scrapers


def run_ats_scrape(
    db: Session,
    platform_toggles: Optional[Dict[str, bool]] = None,
) -> Dict[str, Dict]:
    """Scrape all configured ATS boards and persist results.

    Respects platform toggles when provided. Returns a per-source summary.
    """
    roles = config.target_roles()
    companies = config.ats_companies()
    exclude = config.exclude_companies()
    summary: Dict[str, Dict] = {}

    for scraper in build_scrapers(roles, companies, exclude):
        if platform_toggles is not None and not platform_toggles.get(scraper.source, True):
            summary[scraper.source] = {"skipped": "platform disabled"}
            continue
        try:
            jobs = scraper.scrape()
        except Exception as exc:  # noqa: BLE001 - never let one source break the run
            logger.exception("[%s] scrape failed", scraper.source)
            summary[scraper.source] = {"error": str(exc)}
            continue
        created, seen = persist_scraped_jobs(db, jobs)
        summary[scraper.source] = {"found": seen, "new": created}
    return summary
