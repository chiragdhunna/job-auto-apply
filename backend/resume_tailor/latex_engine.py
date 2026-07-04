"""LaTeX resume generation + compilation.

Public interface (as specified):
    generate_resume(job_description: str, base_resume_data: dict) -> str   # .tex
    compile_latex(tex_string: str) -> bytes                               # PDF bytes

Plus a convenience that ties them to the DB:
    tailor_and_store(db, job) -> ResumeVersion

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
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend import config
from backend.db import crud
from backend.db.models import Job, ResumeVersion
from backend.llm.client import generate
from backend.resume_tailor.prompts import build_tailoring_prompt

logger = logging.getLogger("job_auto_apply.resume")

RESUME_DIR = Path(config.BASE_DIR) / "data" / "resumes"
COMPILE_TIMEOUT = 120


class LatexCompileError(RuntimeError):
    """Raised when no compiler is available or compilation fails."""


# --------------------------------------------------------------------------- #
# Generation                                                                   #
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


def generate_resume(job_description: str, base_resume_data: Dict[str, Any]) -> str:
    """Generate a JD-tailored resume as a LaTeX (.tex) string."""
    resume_json = json.dumps(base_resume_data or {}, ensure_ascii=False, indent=2)
    prompt = build_tailoring_prompt(job_description, resume_json)
    raw = generate(prompt, expect_json=False)
    return _extract_latex(raw)


# --------------------------------------------------------------------------- #
# Compilation                                                                  #
# --------------------------------------------------------------------------- #
def _detect_compiler() -> Optional[str]:
    for name in ("tectonic", "pdflatex"):
        if shutil.which(name):
            return name
    return None


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
                "-output-directory",
                tmp,
                tex_path,
            ]
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


# --------------------------------------------------------------------------- #
# DB-tied convenience                                                          #
# --------------------------------------------------------------------------- #
def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (text or "").strip())[:40] or "resume"


def tailor_and_store(
    db: Session,
    job: Job,
    base_resume_data: Optional[Dict[str, Any]] = None,
) -> ResumeVersion:
    """Generate + compile a tailored resume and record a resume_versions row.

    The .tex is always stored. If compilation fails (or no compiler is present),
    the row is still created with pdf_path=None so the owner can inspect/fix the
    LaTeX from the dashboard.
    """
    if base_resume_data is None:
        base_resume_data = config.load_base_resume_data()

    jd = job.description_raw or f"{job.title} at {job.company}"
    tex = generate_resume(jd, base_resume_data)

    pdf_path: Optional[str] = None
    try:
        pdf_bytes = compile_latex(tex)
        RESUME_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"job_{job.id}_{_safe(job.company)}_{ts}.pdf"
        out = RESUME_DIR / fname
        with open(out, "wb") as f:
            f.write(pdf_bytes)
        pdf_path = str(out.resolve())
        logger.info("Compiled tailored resume for job %s -> %s", job.id, pdf_path)
    except LatexCompileError as exc:
        logger.warning("Resume for job %s generated but not compiled: %s", job.id, exc)

    rv = crud.create_resume_version(db, job_id=job.id, tex_content=tex, pdf_path=pdf_path)
    db.commit()
    return rv
