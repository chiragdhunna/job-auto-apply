"""LinkedIn scraper (browser-driven placeholder).

LinkedIn discovery happens through the authenticated, persistent Playwright
session (Phase 10) — never an anonymous HTTP client — to avoid new-device /
bot flags. This class keeps the scraper interface uniform; the real
search+parse logic lives with `automation/linkedin_apply.py`.
"""

from __future__ import annotations

import logging
from typing import List, Sequence

from backend.db.models import JobSource
from backend.scrapers.base import BaseScraper, ScrapedJob

logger = logging.getLogger("job_auto_apply.scrapers.linkedin")


class LinkedInScraper(BaseScraper):
    source = JobSource.LINKEDIN

    def __init__(self, roles: Sequence[str], locations: Sequence[str] | None = None) -> None:
        self.roles = list(roles or [])
        self.locations = list(locations or [])

    def scrape(self) -> List[ScrapedJob]:
        logger.info(
            "LinkedInScraper is browser-driven; discovery runs via automation/linkedin_apply.py."
        )
        return []
