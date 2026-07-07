"""Arbeitnow job source — https://www.arbeitnow.com/api/job-board-api

Paginated (`data` array + `links.next`). EU-heavy, and carries a
`visa_sponsorship` flag we surface prominently (relevant to the owner's UK goal).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from backend.scrapers.base import ScrapedJob, strip_html
from backend.scrapers.web_common import WebScraper, get_json, location_ok, looks_relevant

logger = logging.getLogger("jobctl.scrapers.web")


class ArbeitnowScraper(WebScraper):
    source = "arbeitnow"
    URL = "https://www.arbeitnow.com/api/job-board-api"
    MAX_PAGES = 3

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        url: Optional[str] = self.URL
        for _ in range(self.MAX_PAGES):
            if not url:
                break
            data = get_json(url)
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
                loc_display = (f"{location} (Remote)" if remote and location
                               else (location or ("Remote" if remote else None)))
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
            url = (data.get("links") or {}).get("next")
        logger.info("[arbeitnow] %d matching jobs", len(out))
        return out
