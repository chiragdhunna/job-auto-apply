"""Remotive job source — https://remotive.com/api/remote-jobs?search={kw}"""

from __future__ import annotations

import logging
from typing import List

from backend.scrapers.base import ScrapedJob, role_keywords, strip_html
from backend.scrapers.web_common import WebScraper, get_json, location_ok, looks_relevant

logger = logging.getLogger("job_auto_apply.scrapers.web")


class RemotiveScraper(WebScraper):
    source = "remotive"
    URL = "https://remotive.com/api/remote-jobs"

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        # Remotive's search matches descriptions (fuzzy), so filter results hard.
        for term in (role_keywords(self.roles) or [""])[:6]:
            data = get_json(self.URL, {"search": term, "limit": 50})
            for j in (data or {}).get("jobs", []) or []:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                category = (j.get("category") or "").lower()
                if category and "software" not in category and "data" not in category:
                    continue
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
