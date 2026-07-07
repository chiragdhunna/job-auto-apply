"""Web-wide job board orchestration.

The individual sources now live in their own modules (remotive_scraper.py,
remoteok_scraper.py, arbeitnow_scraper.py, jobicy_scraper.py, themuse_scraper.py,
adzuna_scraper.py); shared helpers are in web_common.py. This module just wires
them together and gates each by the per-source `sources:` toggles.

Backwards-compatible: `location_ok`, `looks_relevant`, `get_json`, `WebScraper`
are re-exported here so older imports keep working.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend import config
from backend.scrapers.adzuna_scraper import AdzunaScraper
from backend.scrapers.arbeitnow_scraper import ArbeitnowScraper
from backend.scrapers.base import BaseScraper, persist_scraped_jobs
from backend.scrapers.jobicy_scraper import JobicyScraper
from backend.scrapers.remoteok_scraper import RemoteOKScraper
from backend.scrapers.remotive_scraper import RemotiveScraper
from backend.scrapers.themuse_scraper import TheMuseScraper
from backend.scrapers.web_common import (  # noqa: F401 (re-exported for compat)
    WebScraper,
    get_json,
    location_ok,
    looks_relevant,
)

logger = logging.getLogger("jobctl.scrapers.web")

# Order = display order in summaries. Each class carries its own `source` name.
WEB_SCRAPER_CLASSES = [
    RemotiveScraper,
    RemoteOKScraper,
    ArbeitnowScraper,
    JobicyScraper,
    TheMuseScraper,
    AdzunaScraper,
]


def run_web_scrape(
    db: Session,
    source_toggles: Optional[Dict[str, bool]] = None,
) -> Dict[str, Dict]:
    """Scrape the enabled web-wide boards. Gated per-source by `source_toggles`.

    A source with no explicit toggle defaults to enabled.
    """
    toggles = source_toggles if source_toggles is not None else config.source_defaults()
    roles = config.target_roles()
    locations = config.target_locations()
    exclude = config.exclude_companies()

    summary: Dict[str, Dict] = {}
    for cls in WEB_SCRAPER_CLASSES:
        name = cls.source
        if not toggles.get(name, True):
            summary[name] = {"skipped": "source disabled"}
            continue
        scraper: BaseScraper = cls(roles, locations, exclude)
        try:
            jobs = scraper.scrape()
        except Exception as exc:  # noqa: BLE001 — one source must not break the run
            logger.exception("[%s] scrape failed", name)
            summary[name] = {"error": str(exc)}
            continue
        created, seen = persist_scraped_jobs(db, jobs)
        summary[name] = {"found": seen, "new": created}
    return summary
