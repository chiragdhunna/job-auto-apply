"""Abstract scraper interface + shared helpers.

A scraper produces :class:`ScrapedJob` records; :func:`persist_scraped_jobs`
upserts them into the ``jobs`` table (dedup on source+external_id / url).

Role matching (keyword-based): a job title matches if it contains ANY distinctive
keyword drawn from the target roles (case-insensitive, with synonym expansion
like GenAI -> "generative ai" / "llm"). Generic words such as "developer" /
"engineer" / "senior" are ignored so they don't match everything. This favours
recall — the Gemini scorer (Phase 5) provides precision, ranking each match for
true fit before anything is queued for application.
"""

from __future__ import annotations

import html
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from backend.db import crud

logger = logging.getLogger("jobctl.scrapers")

_TAG_RE = re.compile(r"<[^>]+>")
_MULTINEWLINE_RE = re.compile(r"\n\s*\n\s*\n+")

# Words too generic to define a match on their own.
GENERIC_TOKENS = {
    "developer", "engineer", "senior", "junior", "staff", "lead", "principal",
    "sr", "jr", "i", "ii", "iii", "iv", "the", "a", "an", "of", "and", "or",
    "specialist", "associate", "mid", "level",
}

# Token -> phrases that should also count as a match for that token.
ROLE_SYNONYMS = {
    "genai": ["genai", "generative ai", "gen ai", "gen-ai", "llm", "large language model"],
    "ml": ["ml", "machine learning"],
}


@dataclass
class ScrapedJob:
    source: str
    external_id: Optional[str]
    title: str
    company: str
    url: str
    location: Optional[str] = None
    description_raw: Optional[str] = None
    salary_range: Optional[str] = None


def strip_html(raw: Optional[str]) -> Optional[str]:
    """Convert an HTML (possibly entity-escaped) blob to readable plain text."""
    if not raw:
        return raw
    text = html.unescape(raw)          # &lt;div&gt; -> <div>
    text = _TAG_RE.sub(" ", text)       # drop tags
    text = html.unescape(text)          # decode any remaining entities
    text = re.sub(r"[ \t]+", " ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


def significant_tokens(role: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9\+#\.]+", role.lower())
    sig = [t for t in tokens if t not in GENERIC_TOKENS and len(t) > 1]
    return sig or tokens  # if a role is ALL generic words, match on all tokens


def role_keywords(roles: Sequence[str]) -> List[str]:
    """Flatten target roles into the set of distinctive keywords/synonyms to match."""
    phrases: List[str] = []
    seen = set()
    for role in roles:
        for tok in significant_tokens(role):
            for phrase in ROLE_SYNONYMS.get(tok, [tok]):
                if phrase not in seen:
                    seen.add(phrase)
                    phrases.append(phrase)
    return phrases


def title_matches_roles(title: str, roles: Sequence[str]) -> bool:
    if not roles:
        return True
    t = (title or "").lower()
    return any(phrase in t for phrase in role_keywords(roles))


class BaseScraper(ABC):
    """All scrapers implement ``scrape() -> list[ScrapedJob]``."""

    source: str = "base"

    @abstractmethod
    def scrape(self) -> List[ScrapedJob]:  # pragma: no cover - interface
        raise NotImplementedError


def persist_scraped_jobs(db: Session, jobs: Sequence[ScrapedJob]) -> Tuple[int, int]:
    """Upsert scraped jobs. Returns (newly_created, total_seen)."""
    created = 0
    for sj in jobs:
        _, was_created = crud.upsert_job(
            db,
            source=sj.source,
            external_id=sj.external_id,
            title=sj.title,
            company=sj.company,
            location=sj.location,
            url=sj.url,
            description_raw=sj.description_raw,
            salary_range=sj.salary_range,
        )
        if was_created:
            created += 1
    db.commit()
    return created, len(jobs)
