"""Patch-mode resume tailoring — built for local models.

ARCHITECTURE: full-document generation asks an 8B model to do two jobs at once:
decide CONTENT (what to say for this JD) and reproduce FORMAT (a 210-line LaTeX
document, verbatim, with strict structure). Small models are decent at the
first and reliably bad at the second — hence "Missing \\begin{document}" loops.

Patch mode decouples them:
  * the LLM returns ONLY the content deltas as strict JSON (~300 output tokens
    instead of ~2500 → 5-8x faster on CPU, and Ollama's format:"json" makes it
    reliable)
  * code applies the deltas to config/base_resume.tex at its section anchors
    (%== SUMMARY ==%, %== SKILLS ==%, %== EXPERIENCE ==%) deterministically —
    the document structure can NEVER be invalid

Edit surface intentionally matches the owner's own tailoring rules: summary,
skills rows (same labels, same count), and the most-recent-job bullets (same
count). Everything else stays byte-identical. Any failure (bad JSON, missing
anchors) returns None and the caller falls back to full-document generation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from backend.llm.client import generate

logger = logging.getLogger("jobctl.resume.patch")

MAX_JD_CHARS = 4000

_SUMMARY_RE = re.compile(
    r"(%=+ *SUMMARY *=+%.*?\\begin\{onecolentry\}\s*\n)(.*?)(\n\s*\\end\{onecolentry\})",
    re.DOTALL,
)
_SKILLS_REGION_RE = re.compile(r"(%=+ *SKILLS *=+%)(.*?)(%=+ *EXPERIENCE *=+%)", re.DOTALL)
_SKILL_ROW_RE = re.compile(r"(\\item \\textbf\{([^}]*?):?\})([^\n]*)")
_EXP_REGION_RE = re.compile(r"(%=+ *EXPERIENCE *=+%)(.*?)(%=+ *(?:PROJECTS|EDUCATION) *=+%)", re.DOTALL)
_HIGHLIGHTS_RE = re.compile(r"(\\begin\{highlights\})(.*?)(\\end\{highlights\})", re.DOTALL)
_ITEM_RE = re.compile(r"\\item ([^\n]*)")


def _escape(text: str) -> str:
    """LaTeX-escape plain text from the model (idempotent for already-escaped)."""
    return re.sub(r"(?<!\\)([&%#$_])", r"\\\1", (text or "").strip())


def extract_editable(tex: str) -> Optional[Dict[str, Any]]:
    """Pull the three editable regions out of the base resume. None if anchors missing."""
    m_sum = _SUMMARY_RE.search(tex)
    m_skills = _SKILLS_REGION_RE.search(tex)
    m_exp = _EXP_REGION_RE.search(tex)
    if not (m_sum and m_skills and m_exp):
        return None
    skills = [(m.group(2).strip(), m.group(3).strip())
              for m in _SKILL_ROW_RE.finditer(m_skills.group(2))]
    m_hl = _HIGHLIGHTS_RE.search(m_exp.group(2))
    bullets = [m.group(1).strip() for m in _ITEM_RE.finditer(m_hl.group(2))] if m_hl else []
    if not skills or not bullets:
        return None
    return {"summary": m_sum.group(2).strip(), "skills": skills, "bullets": bullets}


def build_patch_prompt(jd: str, current: Dict[str, Any]) -> str:
    jd = (jd or "").strip()[:MAX_JD_CHARS]
    skills_desc = "\n".join(f'  "{label}": "{items}"' for label, items in current["skills"])
    bullets_desc = "\n".join(f"  {i+1}. {b}" for i, b in enumerate(current["bullets"]))
    n_bullets = len(current["bullets"])
    return f"""You are tailoring a resume to a job description. You will rewrite ONLY three
things; everything else in the resume is locked.

JOB DESCRIPTION:
\"\"\"
{jd}
\"\"\"

CURRENT SUMMARY:
{current['summary']}

CURRENT SKILLS ROWS (keep these EXACT labels, rewrite only the comma-separated
items after each; reorder so the most JD-relevant items come first; you may add
JD keywords the candidate plausibly has from context, never fabricate expertise):
{skills_desc}

CURRENT MOST-RECENT-JOB BULLETS (rewrite each to use this JD's terminology while
keeping every real metric; exactly {n_bullets} bullets, each 1-2 lines):
{bullets_desc}

Rules: never invent employers, dates, or credentials. Plain text only — no
LaTeX commands, no markdown. Keep lengths close to the originals (the page
budget is fixed).

Return ONLY this JSON:
{{"summary": "<2-3 line rewritten summary front-loading top JD keywords>",
 "skills": {{{", ".join(f'"{label}": "<items>"' for label, _ in current["skills"])}}},
 "bullets": [{", ".join(f'"<bullet {i+1}>"' for i in range(n_bullets))}]}}"""


def _parse_json(raw: str) -> Dict[str, Any]:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e > s:
            return json.loads(cleaned[s:e + 1])
        raise


def apply_patch(tex: str, current: Dict[str, Any], patch: Dict[str, Any]) -> Optional[str]:
    """Apply deltas at the anchors. Structure is preserved by construction."""
    summary = _escape(str(patch.get("summary") or "")) or None
    skills_in = patch.get("skills") or {}
    bullets_in = [str(b) for b in (patch.get("bullets") or [])]

    out = tex
    if summary:
        out = _SUMMARY_RE.sub(lambda m: m.group(1) + summary + m.group(3), out, count=1)

    if isinstance(skills_in, dict) and skills_in:
        def _skills_region(m):
            body = m.group(2)
            def _row(rm):
                label = rm.group(2).strip()
                new_items = skills_in.get(label)
                if not new_items:
                    return rm.group(0)  # label untouched by model -> keep original
                return rm.group(1) + " " + _escape(str(new_items))
            return m.group(1) + _SKILL_ROW_RE.sub(_row, body) + m.group(3)
        out = _SKILLS_REGION_RE.sub(_skills_region, out, count=1)

    if bullets_in:
        n = len(current["bullets"])
        bullets = ([_escape(b) for b in bullets_in] + [_escape(b) for b in current["bullets"]])[:n]
        def _exp_region(m):
            body = m.group(2)
            def _hl(hm):
                items = iter(bullets)
                new_body = _ITEM_RE.sub(
                    lambda im: "\\item " + next(items, im.group(1)), hm.group(2))
                return hm.group(1) + new_body + hm.group(3)
            return m.group(1) + _HIGHLIGHTS_RE.sub(_hl, body, count=1) + m.group(3)
        out = _EXP_REGION_RE.sub(_exp_region, out, count=1)

    # Sanity: structure must be intact (it is, by construction — verify anyway).
    for marker in (r"\documentclass", r"\begin{document}", r"\end{document}"):
        if marker not in out:
            return None
    return out


def tailor_via_patch(job, jd: str, base_tex: str) -> Optional[str]:
    """Full patch-mode pass. Returns tailored tex, or None to fall back.

    Raises LLMError upward (provider outage handling stays with the caller).
    """
    current = extract_editable(base_tex)
    if not current:
        logger.warning("Patch mode: section anchors not found in base_resume.tex — falling back.")
        return None
    raw = generate(build_patch_prompt(jd, current), expect_json=True)
    try:
        patch = _parse_json(raw)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Patch mode: model returned unparseable JSON — falling back.")
        return None
    result = apply_patch(base_tex, current, patch)
    if result is None:
        logger.warning("Patch mode: applying deltas failed — falling back.")
        return None
    logger.info("Patch-mode tailoring succeeded for job %s (summary+%d skills rows+%d bullets).",
                job.id, len(patch.get("skills") or {}), len(patch.get("bullets") or []))
    return result
