"""Custom question -> answer generation.

Given a JD + a set of questions (the common ones by default, or the actual
questions scraped from an application form), generate concise answers grounded in
``base_resume_data.json``. Routes through the shared LLM client and returns a
dict keyed by question. Never invents facts about the candidate.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from backend import config
from backend.db.models import Job
from backend.llm.client import generate

logger = logging.getLogger("jobctl.answers")

MAX_JD_CHARS = 4000
DEFAULT_MAX_WORDS = 150

# The common question types called out in the spec (key -> prompt text).
DEFAULT_QUESTIONS: Dict[str, str] = {
    "why_this_company": "Why do you want to work at this company?",
    "why_this_role": "Why are you a strong fit for this role?",
    "biggest_challenge": "Describe a challenging problem you solved and how you approached it.",
}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:50] or "question"


def _normalize_questions(
    questions: Optional[Union[Dict[str, str], List[str]]]
) -> Dict[str, str]:
    if not questions:
        return dict(DEFAULT_QUESTIONS)
    if isinstance(questions, dict):
        return {k: v for k, v in questions.items() if v}
    # list of raw question strings -> keyed by slug (kept unique)
    out: Dict[str, str] = {}
    for q in questions:
        if not q:
            continue
        key = _slug(q)
        n = 2
        base = key
        while key in out:
            key = f"{base}_{n}"
            n += 1
        out[key] = q
    return out


def _extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def build_answers_prompt(
    job: Job,
    base_resume_data: Dict[str, Any],
    questions: Dict[str, str],
    max_words: int,
) -> str:
    resume_json = json.dumps(base_resume_data or {}, ensure_ascii=False, indent=2)
    description = (job.description_raw or "").strip()
    if len(description) > MAX_JD_CHARS:
        description = description[:MAX_JD_CHARS] + "\n...[truncated]"
    q_lines = "\n".join(f'  "{key}": {text!r}' for key, text in questions.items())
    return f"""You are helping a candidate answer job-application questions. Ground every
answer ONLY in the candidate's real background below — never invent employers,
projects, metrics, or credentials that are not present.

CANDIDATE PROFILE (JSON):
{resume_json}

JOB
Title: {job.title}
Company: {job.company}
Location: {job.location or "Not specified"}
Description:
\"\"\"
{description or "No description available."}
\"\"\"

Write a first-person answer to each question below (roughly {max_words} words
each, specific and genuine, no clichés). Keys identify each question:
{q_lines}

Return ONLY a JSON object mapping each key to its answer string, e.g.
{{ "some_key": "the answer", ... }}"""


def generate_answers(
    job: Job,
    base_resume_data: Optional[Dict[str, Any]] = None,
    questions: Optional[Union[Dict[str, str], List[str]]] = None,
    max_words: int = DEFAULT_MAX_WORDS,
) -> Dict[str, str]:
    """Return {question_key: answer}. Raises LLMError / ValueError on failure."""
    if base_resume_data is None:
        base_resume_data = config.load_base_resume_data()
    q = _normalize_questions(questions)
    prompt = build_answers_prompt(job, base_resume_data, q, max_words)
    raw = generate(prompt, expect_json=True)
    data = _extract_json_object(raw)

    answers: Dict[str, str] = {}
    for key in q:
        val = data.get(key)
        if val is None:
            # tolerate models that key by the question text instead of the slug
            val = data.get(q[key])
        if val is not None:
            answers[key] = str(val).strip()
    # If the model returned a completely different shape, fall back to raw dict.
    if not answers and isinstance(data, dict):
        answers = {str(k): str(v).strip() for k, v in data.items()}
    logger.info("Generated %d answers for job %s '%s'", len(answers), job.id, job.title[:40])
    return answers
