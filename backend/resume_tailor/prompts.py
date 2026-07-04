"""Resume-tailoring prompt templates.

Placeholders ``{job_description}`` and ``{base_resume_data}`` are substituted via
simple string replacement (NOT ``str.format``), so your prompt can contain all
the literal LaTeX braces it needs without escaping them.
"""

# ============================================================================
# PASTE OWNER'S LATEX PROMPT HERE
# ----------------------------------------------------------------------------
# Paste your existing, battle-tested LaTeX resume-tailoring prompt between the
# triple quotes below. Keep the two placeholders somewhere in the text:
#     {job_description}   -> the target job description
#     {base_resume_data}  -> your structured resume data (JSON)
# Leave this empty ("") to use DEFAULT_LATEX_PROMPT instead.
# ============================================================================
OWNER_LATEX_PROMPT = ""


# A sensible default so the system works out of the box before you paste yours.
DEFAULT_LATEX_PROMPT = r"""You are an expert resume writer and LaTeX typesetter. Produce a single-page,
ATS-friendly resume in LaTeX, tailored to the job description below.

Rules:
- Output ONLY the LaTeX source: a complete, compilable document from
  \documentclass to \end{document}. No commentary, no markdown fences.
- Use only widely-available packages that compile under pdflatex: geometry,
  enumitem, titlesec, hyperref, xcolor. Do NOT use fontspec, minted, or any
  package requiring shell-escape or xelatex/lualatex.
- Keep it to one page. Use concise, quantified bullet points.
- Reorder and rephrase the candidate's real experience/skills to emphasise what
  this job values most. Never invent employers, dates, or credentials that are
  not present in the candidate data.
- Escape LaTeX special characters (& % $ # _ { } ~ ^) in any generated text.

JOB DESCRIPTION:
{job_description}

CANDIDATE DATA (JSON):
{base_resume_data}

Return the LaTeX source now."""


def build_tailoring_prompt(job_description: str, base_resume_data_json: str) -> str:
    """Inject the JD + resume JSON into the active prompt template.

    Uses ``str.replace`` (not ``.format``) so literal LaTeX braces are safe.
    """
    template = (OWNER_LATEX_PROMPT or "").strip() or DEFAULT_LATEX_PROMPT
    return (
        template
        .replace("{job_description}", job_description or "")
        .replace("{base_resume_data}", base_resume_data_json or "{}")
    )
