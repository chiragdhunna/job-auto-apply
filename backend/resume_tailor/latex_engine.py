"""LaTeX resume generation + compilation.

Public interface (as specified):
    generate_resume(job_description: str, base_resume_data: dict) -> str   # .tex
    compile_latex(tex_string: str) -> bytes                               # PDF bytes

Plus a convenience that ties them to the DB:
    tailor_and_store(db, job) -> ResumeVersion

Robustness pipeline (local models emit broken LaTeX more often than Gemini):

    generate  -> structural validation (one corrective LLM pass if invalid)
    compile   -> on failure, up to RESUME_REPAIR_ATTEMPTS LLM repair passes
    fallback  -> if still failing, compile the owner's untailored
                 config/base_resume.tex so a valid PDF is ALWAYS produced
                 (an untailored application beats no application)

generate_resume routes through the shared LLM client (Gemini -> Ollama fallback).
compile_latex shells out to `tectonic` (preferred) or `pdflatex`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from backend import config
from backend.db import crud
from backend.db.models import Job, ResumeVersion
from backend.llm.client import generate
from backend.resume_tailor.prompts import build_repair_prompt, build_tailoring_prompt

logger = logging.getLogger("jobctl.resume")

RESUME_DIR = Path(config.BASE_DIR) / "data" / "resumes"
BASE_RESUME_TEX_PATH = Path(config.BASE_DIR) / "config" / "base_resume.tex"
COMPILE_TIMEOUT = config.LATEX_COMPILE_TIMEOUT  # env: LATEX_COMPILE_TIMEOUT
MAX_JD_CHARS = 6000  # keep the tailoring prompt bounded (esp. for local models)


class LatexCompileError(RuntimeError):
    """Raised when no compiler is available or compilation fails."""


# --------------------------------------------------------------------------- #
# Extraction + validation                                                      #
# --------------------------------------------------------------------------- #
def _extract_latex(raw: str) -> str:
    """Pull clean LaTeX out of a model response (strip fences / surrounding prose)."""
    if not raw:
        raise ValueError("empty LLM response")
    text = raw.strip()
    # Strip ```latex ... ``` / ``` ... ``` fences.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    # If there's a full document, extract exactly it.
    start = text.find(r"\documentclass")
    if start != -1:
        end = text.rfind(r"\end{document}")
        if end != -1:
            return text[start : end + len(r"\end{document}")].strip()
        return text[start:].strip()
    return text


_REQUIRED_MARKERS = (r"\documentclass", r"\begin{document}", r"\end{document}")


def _missing_markers(tex: str) -> list:
    """Structural sanity check: which required LaTeX markers are absent."""
    return [m for m in _REQUIRED_MARKERS if m not in (tex or "")]


def _structural_problems(tex: str) -> list:
    """All structural problems, not just missing markers.

    Local models sometimes emit documents where every marker is *present* but
    in the wrong order (e.g. \\section content before \\begin{document}) —
    presence checks alone pass, then pdflatex fails with
    "Missing \\begin{document}". Check order too.
    """
    tex = tex or ""
    problems = [f"missing {m}" for m in _missing_markers(tex)]
    if problems:
        return problems
    dc = tex.find(r"\documentclass")
    bd = tex.find(r"\begin{document}")
    ed = tex.rfind(r"\end{document}")
    if not (dc < bd < ed):
        problems.append(
            r"markers are out of order — \documentclass must come first, then "
            r"\begin{document}, then the content, then \end{document}"
        )
    first_section = tex.find(r"\section")
    if first_section != -1 and first_section < bd:
        problems.append(
            r"body content (\section ...) appears BEFORE \begin{document}; all "
            r"visible content must come after \begin{document}"
        )
    return problems


# --------------------------------------------------------------------------- #
# Generation                                                                   #
# --------------------------------------------------------------------------- #
def _load_base_resume_latex() -> Optional[str]:
    """Read the owner's real LaTeX resume source, if present.

    Looked up at config/base_resume.tex. Returns None if the file doesn't
    exist, so callers can fall back to JSON-based prompts.
    """
    if BASE_RESUME_TEX_PATH.exists():
        return BASE_RESUME_TEX_PATH.read_text(encoding="utf-8")
    return None


def generate_resume(job_description: str, base_resume_data: Dict[str, Any]) -> str:
    """Generate a JD-tailored resume as a LaTeX (.tex) string.

    The owner's real LaTeX resume (config/base_resume.tex) is preferred as the
    source representation; falls back to the structured JSON for prompts that
    expect it. Local models sometimes emit structurally broken documents
    (content before ``\\begin{document}`` or missing it entirely) — if the
    output fails the structural check, one corrective pass is requested.
    """
    resume_repr = _load_base_resume_latex()
    if resume_repr is None:
        # Fall back to JSON for prompts (like DEFAULT_LATEX_PROMPT) that expect it.
        resume_repr = json.dumps(base_resume_data or {}, ensure_ascii=False, indent=2)
    prompt = build_tailoring_prompt(job_description, resume_repr)
    raw = generate(prompt, expect_json=False)
    tex = _extract_latex(raw)

    problems = _structural_problems(tex)
    if problems:
        logger.warning(
            "Generated LaTeX is structurally invalid (%s) — requesting a "
            "corrected document from the LLM.",
            "; ".join(problems),
        )
        problem = (
            "The document has structural problems: "
            + "; ".join(problems)
            + ". All visible text must appear between \\begin{document} and "
            "\\end{document}, and the document must be complete."
        )
        raw2 = generate(build_repair_prompt(tex, problem), expect_json=False)
        tex2 = _extract_latex(raw2)
        if not _structural_problems(tex2):
            return tex2
        logger.warning("Corrected document is still structurally invalid; keeping best effort.")
        if len(_structural_problems(tex2)) < len(problems):
            return tex2
    return tex


# --------------------------------------------------------------------------- #
# Compilation                                                                  #
# --------------------------------------------------------------------------- #
def _detect_compiler() -> Optional[str]:
    for name in ("tectonic", "pdflatex"):
        if shutil.which(name):
            return name
    return None


_IS_MIKTEX: Optional[bool] = None


def _is_miktex() -> bool:
    """Detect the MiKTeX distribution (needs --enable-installer to not hang).

    MiKTeX's default "ask me before installing packages" setting pops a GUI
    dialog that a background process can never answer — pdflatex then blocks
    until our timeout kills it. --enable-installer makes missing packages
    install automatically instead.
    """
    global _IS_MIKTEX
    if _IS_MIKTEX is None:
        try:
            proc = subprocess.run(
                ["pdflatex", "--version"], capture_output=True, text=True, timeout=20
            )
            _IS_MIKTEX = "miktex" in ((proc.stdout or "") + (proc.stderr or "")).lower()
        except Exception:  # noqa: BLE001
            _IS_MIKTEX = False
    return _IS_MIKTEX


def compile_latex(tex_string: str) -> bytes:
    """Compile a LaTeX string to PDF bytes using tectonic or pdflatex.

    Raises LatexCompileError if no compiler is installed or compilation fails.
    """
    compiler = _detect_compiler()
    if not compiler:
        raise LatexCompileError(
            "No LaTeX compiler found. Install `tectonic` (recommended, single "
            "binary from https://tectonic-typesetting.github.io) or a TeX "
            "distribution providing `pdflatex`."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = os.path.join(tmp, "resume.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_string)

        if compiler == "tectonic":
            cmds = [["tectonic", "--keep-logs", "--outdir", tmp, tex_path]]
        else:
            # pdflatex often needs two passes to resolve references.
            base_cmd = [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
            ]
            if _is_miktex():
                # Auto-install missing packages instead of blocking on a GUI
                # dialog (which times out headless runs).
                base_cmd.append("--enable-installer")
            base_cmd += ["-output-directory", tmp, tex_path]
            cmds = [base_cmd, base_cmd]

        last_output = ""
        for cmd in cmds:
            try:
                proc = subprocess.run(
                    cmd, cwd=tmp, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
                )
            except subprocess.TimeoutExpired as exc:
                raise LatexCompileError(f"{compiler} timed out after {COMPILE_TIMEOUT}s") from exc
            last_output = (proc.stdout or "") + (proc.stderr or "")

        pdf_path = os.path.join(tmp, "resume.pdf")
        if not os.path.exists(pdf_path):
            raise LatexCompileError(
                f"{compiler} did not produce a PDF. Tail of output:\n{last_output[-1200:]}"
            )
        with open(pdf_path, "rb") as f:
            return f.read()


def _compile_with_repair(tex: str) -> Tuple[Optional[bytes], str]:
    """Compile; on failure, ask the LLM to repair (up to RESUME_REPAIR_ATTEMPTS).

    Returns (pdf_bytes | None, tex_actually_used).
    """
    try:
        return compile_latex(tex), tex
    except LatexCompileError as exc:
        last_error = str(exc)
        logger.warning("LaTeX compile failed: %s", last_error[-400:])

    current = tex
    for attempt in range(1, max(0, config.RESUME_REPAIR_ATTEMPTS) + 1):
        logger.info(
            "Requesting LaTeX repair from the LLM (attempt %d/%d)…",
            attempt,
            config.RESUME_REPAIR_ATTEMPTS,
        )
        try:
            raw = generate(build_repair_prompt(current, last_error[-1500:]), expect_json=False)
            fixed = _extract_latex(raw)
        except Exception:  # noqa: BLE001 — repair is best-effort; fallback follows
            logger.exception("LaTeX repair generation failed; skipping to fallback.")
            break
        fixed_problems = _structural_problems(fixed)
        if fixed_problems:
            logger.warning(
                "Repaired LaTeX still structurally invalid (%s).",
                "; ".join(fixed_problems),
            )
            current = fixed
            last_error = "Document has structural problems: " + "; ".join(fixed_problems)
            continue
        try:
            return compile_latex(fixed), fixed
        except LatexCompileError as exc:
            last_error = str(exc)
            current = fixed
            logger.warning("Repaired LaTeX still fails to compile: %s", last_error[-400:])
    return None, tex


def _fallback_base_resume_tex() -> Optional[str]:
    """The owner's untailored base resume, with the known template fix applied.

    The owner's prompt mandates deleting the `\\vspace{2pt}` immediately before
    the SUMMARY section comment (it pushes Education to page 2), so the same
    fix is applied deterministically here.
    """
    tex = _load_base_resume_latex()
    if not tex:
        return None
    tex = re.sub(r"(?m)^[ \t]*\\vspace\{2pt\}[ \t]*\n(?=\s*%=+ *SUMMARY)", "", tex)
    return tex


# --------------------------------------------------------------------------- #
# DB-tied convenience                                                          #
# --------------------------------------------------------------------------- #
def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip())[:40] or "resume"


def _store_version(db: Session, job: Job, tex: str, pdf_bytes: Optional[bytes]) -> ResumeVersion:
    """Persist a resume_versions row (+ PDF file when we have bytes)."""
    pdf_path: Optional[str] = None
    if pdf_bytes:
        RESUME_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"job_{job.id}_{_safe(job.company)}_{ts}.pdf"
        out = RESUME_DIR / fname
        with open(out, "wb") as f:
            f.write(pdf_bytes)
        pdf_path = str(out.resolve())
        logger.info("Compiled resume for job %s -> %s", job.id, pdf_path)
    rv = crud.create_resume_version(db, job_id=job.id, tex_content=tex, pdf_path=pdf_path)
    db.commit()
    return rv


def tailor_and_store(
    db: Session,
    job: Job,
    base_resume_data: Optional[Dict[str, Any]] = None,
    force_tailor: bool = False,
) -> ResumeVersion:
    """Generate + compile a tailored resume and record a resume_versions row.

    Pipeline: tailored LaTeX -> compile -> LLM repair pass(es) -> untailored
    base-resume fallback. The .tex actually used is always stored; if nothing
    compiles (e.g. no LaTeX engine installed) the row is created with
    pdf_path=None so the owner can inspect/fix from the dashboard.

    ``force_tailor=True`` bypasses RESUME_MODE=base_only — used by the
    dashboard's on-demand "tailor resume for this job" button.
    """
    if base_resume_data is None:
        base_resume_data = config.load_base_resume_data()

    # Deterministic mode: skip LLM tailoring entirely, always attach the
    # compiled base resume. Fast, reliable, zero LLM calls.
    if config.RESUME_MODE == "base_only" and not force_tailor:
        base_tex = _fallback_base_resume_tex()
        if base_tex:
            pdf_bytes = None
            try:
                pdf_bytes = compile_latex(base_tex)
            except LatexCompileError as exc:
                logger.error(
                    "RESUME_MODE=base_only: base resume failed to compile: %s",
                    str(exc)[-400:],
                )
            noted = (
                "% NOTE: RESUME_MODE=base_only — untailored base resume attached.\n"
                + base_tex
            )
            return _store_version(db, job, noted, pdf_bytes)
        logger.warning(
            "RESUME_MODE=base_only but config/base_resume.tex is missing — "
            "using the normal tailoring pipeline instead."
        )

    jd = (job.description_raw or f"{job.title} at {job.company}").strip()
    if len(jd) > MAX_JD_CHARS:
        jd = jd[:MAX_JD_CHARS] + "\n...[truncated]"

    # Strategy: patch mode (content deltas applied to the base template — fast,
    # structurally bulletproof, built for Ollama) vs full-document generation.
    tex: Optional[str] = None
    strategy = config.RESUME_TAILOR_STRATEGY
    if strategy == "auto":
        strategy = "patch" if config.active_provider_name() == "ollama" else "full"
    if strategy == "patch":
        base_tex = _load_base_resume_latex()
        if base_tex:
            from backend.resume_tailor.patch_engine import tailor_via_patch
            tex = tailor_via_patch(job, jd, base_tex)  # None -> fall back to full
            if tex is None:
                logger.warning("Patch-mode tailoring unavailable for job %s — using "
                               "full-document generation.", job.id)
        else:
            logger.warning("RESUME_TAILOR_STRATEGY=patch needs config/base_resume.tex "
                           "— using full-document generation.")
    if tex is None:
        tex = generate_resume(jd, base_resume_data)
    final_tex = tex
    pdf_bytes: Optional[bytes] = None

    compiler = _detect_compiler()
    if compiler is None:
        logger.warning(
            "No LaTeX compiler found — storing .tex only for job %s. Install "
            "`tectonic` or `pdflatex` to produce PDFs.",
            job.id,
        )
    else:
        pdf_bytes, final_tex = _compile_with_repair(tex)
        if pdf_bytes is None:
            base_tex = _fallback_base_resume_tex()
            if base_tex:
                logger.warning(
                    "Tailored LaTeX unusable after repair for job %s — falling "
                    "back to the untailored base resume (config/base_resume.tex).",
                    job.id,
                )
                try:
                    pdf_bytes = compile_latex(base_tex)
                    final_tex = (
                        "% NOTE: tailored generation failed to compile — this is the\n"
                        "% untailored base resume, used as a fallback for this job.\n"
                        + base_tex
                    )
                except LatexCompileError as exc:
                    logger.error(
                        "Fallback base resume ALSO failed to compile: %s "
                        "(check that its packages are installed — run pdflatex "
                        "on config/base_resume.tex once manually)",
                        str(exc)[-400:],
                    )
                    final_tex = tex  # keep the LLM output for debugging
            else:
                logger.warning(
                    "No config/base_resume.tex available for fallback — job %s "
                    "gets .tex only.",
                    job.id,
                )

    return _store_version(db, job, final_tex, pdf_bytes)
