"""RemoteOK job source — https://remoteok.com/api

Returns a JSON array; the first element is a legal-notice object (skipped).
"""

from __future__ import annotations

import logging
from typing import List

from backend.scrapers.base import ScrapedJob, strip_html
from backend.scrapers.web_common import WebScraper, get_json, location_ok, looks_relevant

logger = logging.getLogger("job_auto_apply.scrapers.web")


class RemoteOKScraper(WebScraper):
    source = "remoteok"
    URL = "https://remoteok.com/api"

    def scrape(self) -> List[ScrapedJob]:
        data = get_json(self.URL)
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
