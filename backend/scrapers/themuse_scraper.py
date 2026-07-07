"""The Muse job source — https://www.themuse.com/api/public/jobs

Supports `category` and `page` params. We pull the engineering/data categories,
so engineer-type titles are accepted even without an exact keyword hit.
"""

from __future__ import annotations

import logging
from typing import List

from backend.scrapers.base import ScrapedJob, strip_html, title_matches_roles
from backend.scrapers.web_common import ROLE_WORDS, WebScraper, get_json, location_ok

logger = logging.getLogger("jobctl.scrapers.web")


class TheMuseScraper(WebScraper):
    source = "themuse"
    URL = "https://www.themuse.com/api/public/jobs"
    PAGES = 3
    CATEGORIES = ("Software Engineering", "Data and Analytics")

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        for category in self.CATEGORIES:
            for page in range(1, self.PAGES + 1):
                data = get_json(self.URL, {"category": category, "page": page})
                for j in (data or {}).get("results", []) or []:
                    jid = str(j.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    title = j.get("name") or ""
                    company = (j.get("company") or {}).get("name") or "Unknown"
                    locs = [l.get("name", "") for l in (j.get("locations") or [])]
                    location = "; ".join(x for x in locs if x) or None
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
