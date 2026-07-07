"""Jobicy job source — free public JSON API, no auth.

    https://jobicy.com/api/v2/remote-jobs?count=50&tag={kw}&geo={geo}

Remote-focused board. We query once per target-role keyword (the `tag` param),
filter on title relevance + location, and dedupe by job id. Response shape:
{"jobs": [{id, jobTitle, companyName, jobGeo, url, jobDescription (HTML),
           jobExcerpt, jobLevel, jobType, jobIndustry, jobSlug, pubDate}]}
"""

from __future__ import annotations

import logging
from typing import List

from backend.scrapers.base import ScrapedJob, role_keywords, strip_html
from backend.scrapers.web_common import WebScraper, get_json, location_ok, looks_relevant

logger = logging.getLogger("job_auto_apply.scrapers.web")


class JobicyScraper(WebScraper):
    source = "jobicy"
    URL = "https://jobicy.com/api/v2/remote-jobs"

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        for term in (role_keywords(self.roles) or [""])[:6]:
            data = get_json(self.URL, {"count": 50, "tag": term})
            for j in (data or {}).get("jobs", []) or []:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                title = j.get("jobTitle") or ""
                company = j.get("companyName") or "Unknown"
                location = j.get("jobGeo")
                # Jobicy has no free-text tag array; use industry/level as hints.
                hints = [j.get("jobIndustry"), j.get("jobLevel")]
                hints = [h for h in hints if isinstance(h, str)]
                if not looks_relevant(title, hints, self.roles):
                    continue
                if company.lower() in self.exclude or not location_ok(location, self.locations):
                    continue
                out.append(ScrapedJob(
                    source=self.source,
                    external_id=jid,
                    title=title,
                    company=company,
                    url=j.get("url") or "",
                    location=location or "Remote",
                    description_raw=strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
                ))
        logger.info("[jobicy] %d matching jobs", len(out))
        return out
