"""Jobicy job source — free public JSON API, no auth.

    https://jobicy.com/api/v2/remote-jobs?count=100

Remote-focused board. Jobicy's optional `tag` param 404s on any tag outside its
own taxonomy (e.g. "genai", "flutter"), so we DON'T use it — we fetch the recent
feed once and filter client-side on title relevance + location (same pattern as
RemoteOK). This avoids noisy 404s entirely. Response shape:
{"jobs": [{id, jobTitle, companyName, jobGeo, url, jobDescription (HTML),
           jobExcerpt, jobLevel, jobType, jobIndustry, jobSlug, pubDate}]}
"""

from __future__ import annotations

import logging
from typing import List

from backend.scrapers.base import ScrapedJob, strip_html, title_matches_roles
from backend.scrapers.web_common import ROLE_WORDS, WebScraper, get_json, location_ok

logger = logging.getLogger("jobctl.scrapers.web")


class JobicyScraper(WebScraper):
    source = "jobicy"
    URL = "https://jobicy.com/api/v2/remote-jobs"

    def scrape(self) -> List[ScrapedJob]:
        out: List[ScrapedJob] = []
        seen = set()
        # No `tag` param — it 404s on unknown tags. Fetch the feed, filter locally.
        data = get_json(self.URL, {"count": 100})
        for j in (data or {}).get("jobs", []) or []:
            jid = str(j.get("id"))
            if jid in seen:
                continue
            seen.add(jid)
            title = j.get("jobTitle") or ""
            company = j.get("companyName") or "Unknown"
            location = j.get("jobGeo")
            # Tagless feed isn't pre-filtered to tech, so accept target-keyword
            # titles OR any engineer/developer-type title (recall); the LLM
            # scorer is the precision layer that down-ranks irrelevant roles.
            t = title.lower()
            if not (title_matches_roles(title, self.roles) or any(w in t for w in ROLE_WORDS)):
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
