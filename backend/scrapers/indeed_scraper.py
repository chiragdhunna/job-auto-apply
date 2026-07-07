"""Indeed scraper (browser-driven placeholder).

Indeed has no clean public JSON API and actively blocks scraping, so discovery
is done through the authenticated Playwright session used for applying (Phase 11)
rather than an HTTP client. This class keeps the scraper interface uniform; the
real search+parse logic lives with `automation/indeed_apply.py`.
"""

from __future__ import annotations

import logging
from typing import List, Sequence

from backend.db.models import JobSource
from backend.scrapers.base import BaseScraper, ScrapedJob

logger = logging.getLogger("jobctl.scrapers.indeed")


class IndeedScraper(BaseScraper):
    source = JobSource.INDEED

    def __init__(self, roles: Sequence[str], locations: Sequence[str] | None = None) -> None:
        self.roles = list(roles or [])
        self.locations = list(locations or [])

    def scrape(self) -> List[ScrapedJob]:
        logger.info(
            "IndeedScraper is browser-driven; discovery runs via automation/indeed_apply.py."
        )
        return []
