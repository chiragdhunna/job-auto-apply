"""Adzuna job source — https://api.adzuna.com/v1/api/jobs/{cc}/search/1

Free tier, requires ADZUNA_APP_ID / ADZUNA_APP_KEY (https://developer.adzuna.com).
Strong UK/India coverage. No-op when keys are absent.
"""

from __future__ import annotations

import logging
from typing import List

from backend import config
from backend.scrapers.base import ScrapedJob, title_matches_roles
from backend.scrapers.web_common import WebScraper, get_json


class AdzunaScraper(WebScraper):
    source = "adzuna"
    URL = "https://api.adzuna.com/v1/api/jobs/{cc}/search/1"
    COUNTRY_FOR_TARGET = {"united kingdom": "gb", "india": "in", "remote": "gb"}

    def _countries(self) -> List[str]:
        ccs: List[str] = []
        for t in (self.locations or ["united kingdom"]):
            cc = self.COUNTRY_FOR_TARGET.get(t.lower().strip())
            if cc and cc not in ccs:
                ccs.append(cc)
        return ccs or ["gb"]

    def scrape(self) -> List[ScrapedJob]:
        logger = logging.getLogger("job_auto_apply.scrapers.web")
        if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
            logger.info("[adzuna] skipped — ADZUNA_APP_ID/KEY not set")
            return []
        out: List[ScrapedJob] = []
        seen = set()
        for cc in self._countries():
            for role in (self.roles or [""]):
                data = get_json(self.URL.format(cc=cc), {
                    "app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
                    "what": role, "results_per_page": 25,
                })
                for j in (data or {}).get("results", []) or []:
                    jid = str(j.get("id"))
                    if jid in seen:
                        continue
                    seen.add(jid)
                    title = j.get("title") or ""
                    company = (j.get("company") or {}).get("display_name") or "Unknown"
                    if not title_matches_roles(title, self.roles):
                        continue
                    if company.lower() in self.exclude:
                        continue
                    salary = None
                    smin, smax = j.get("salary_min"), j.get("salary_max")
                    if smax:
                        salary = f"{int(smin or 0):,} - {int(smax):,}"
                    out.append(ScrapedJob(
                        source=self.source, external_id=jid, title=title, company=company,
                        url=j.get("redirect_url") or "",
                        location=(j.get("location") or {}).get("display_name"),
                        description_raw=j.get("description"), salary_range=salary,
                    ))
        logger.info("[adzuna] %d matching jobs", len(out))
        return out
