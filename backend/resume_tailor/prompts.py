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
OWNER_LATEX_PROMPT = r"""You are an expert technical resume writer and ATS (Applicant Tracking System) specialist.
Your task is to tailor my existing LaTeX resume to maximally match a target Job Description (JD)
to increase my chances of passing both ATS screening and human review.

---

## MY RESUME (LaTeX code)
{base_resume_data}

---

## TARGET JOB DESCRIPTION
{job_description}

---

## YOUR TASK

### STEP 1 — Analyze the JD deeply
Before touching the resume, extract and categorize every keyword from the JD into:

1. **Must-have technical skills** — explicitly required, mentioned multiple times, or in the
   "required" section (e.g., RAG, LLMs, Python, AWS)
2. **Preferred/nice-to-have skills** — in "preferred" or "nice to have" sections
3. **Domain buzzwords** — industry-specific terminology the JD uses heavily
   (e.g., "agentic AI", "multi-step reasoning", "tool calling", "orchestration")
4. **Soft skills / work style keywords** — (e.g., "cross-functional", "production-grade",
   "POC to production", "technical leadership")
5. **Keywords MISSING from my resume** — compare extracted JD keywords against my resume
   and list exactly what is absent

### STEP 2 — Budget your space BEFORE writing anything
This is mandatory and must be done before any LaTeX is written.

My resume template has a fixed vertical budget. Count how many lines/rows each section
currently occupies in my resume, then plan your changes within that same budget.
Use this exact accounting framework:

| Section            | Current line count | Planned line count | Delta |
|--------------------|--------------------|--------------------|-------|
| Header             | (count it)         | (no change)        | 0     |
| Summary            | (count it)         | (your plan)        | ±N    |
| Skills             | (count rows)       | (your plan)        | ±N    |
| TCS bullets        | (count it)         | (no change — 4)    | 0     |
| BlueMango SDE      | (count it)         | (no change)        | 0     |
| BlueMango Intern   | (count it)         | (no change)        | 0     |
| Projects           | (count it)         | (no change)        | 0     |
| Education          | (count it)         | (no change)        | 0     |
| **TOTAL DELTA**    |                    |                    | **must be 0 or negative** |

**The total delta must be zero or negative — meaning you cannot add more lines than
you remove. If you want to add a new Skills row, you must remove a different row or
shorten an existing one by an equivalent number of lines.**

The single most common page-overflow mistake is expanding the Skills section
(adding new rows) without removing an equivalent number of lines elsewhere.
You must explicitly account for every line added and every line removed.

**Template fix (apply always):** Remove the line `\vspace{2pt}` that appears
immediately before the `%================== SUMMARY ==================%` comment
in the LaTeX code. This line adds unnecessary vertical space and will push Education
to page 2. Delete it in every output, unconditionally, regardless of content length.

### STEP 3 — Plan your changes
After completing the space budget, state:
- Which sections you will modify and why
- Which sections you will NOT touch and why
- What keywords you are injecting and exactly where
- Exactly how many Skills rows you will use (must match original count or fewer)
- How you will keep the total line count neutral or negative

Obey these hard rules during planning:
- The resume MUST remain exactly 1 page — this is the single most important constraint
- Education must appear on page 1 — if it does not, something above it is too long
- Do NOT fabricate projects, companies, degrees, or metrics that don't exist
- Do NOT change BlueMango Labs bullets or the Projects section content
- You MAY rewrite TCS/most-recent-job bullets since it is ongoing and I am actively
  working on these technologies in that role
- Every keyword injection must sound natural and credible, not keyword-stuffed
- Prioritize injecting keywords into: Summary > Most Recent Job > Skills
  (in that order of impact for ATS)
- **Skills section hard rule: use the SAME number of rows as the original resume
  or fewer. Never add a net new row without explicitly removing another.**
  Merge new keywords into existing rows rather than creating new rows whenever possible.

### STEP 4 — Rewrite the resume
Apply all planned changes and produce the complete updated LaTeX code.

Specifically:

1. **Professional Summary** — Rewrite to front-load the top 5-6 JD keywords naturally.
   Keep it to 2-3 lines max. Must not be longer than the original summary.

2. **Skills Section** — Restructure to include missing must-have and preferred keywords.
   Rules:
   - Use the SAME number of bullet rows as the original (count them before editing)
   - Merge new keywords into existing rows — do not add net new rows
   - Reorder skills so most JD-relevant appear first within each category
   - Move the most JD-critical language to the front of its list
   - If a row from the original is now irrelevant to this JD, repurpose it — don't
     keep it AND add a new one

3. **Most Recent Job (TCS or equivalent)** — This is your highest-leverage section.
   Rewrite all 4 bullets to:
   - Use exact JD terminology and phrasing where possible
   - Each bullet targets a different cluster of JD requirements
   - Preserve all real metrics (uptime %, latency reduction %, user counts)
     but reframe the context around new keywords
   - Keep each bullet to 1–2 lines in the compiled PDF — never let a bullet wrap
     to a 3rd line. If it wraps, trim it.
   - Use action verbs the JD implies: "Architected", "Designed", "Implemented",
     "Deployed", "Evaluated", "Integrated"

4. **Older Jobs / Projects / Education** — Leave content unchanged.
   Only make micro-edits (trim a word here or there) if needed purely for space.

5. **Page constraint enforcement — trim priority order if over budget:**
   - First: shorten/merge Skills rows
   - Second: trim BlueMango Intern bullets (least impactful section)
   - Third: trim Project bullets
   - Never trim the most recent job or the Skills section keywords
   - Never reduce font size, margins, or spacing values in the LaTeX preamble

### STEP 5 — Self-check before outputting
Before writing the final LaTeX, answer these questions internally:

- Did I delete `\vspace{2pt}` before the Summary section? If no → delete it now
- Did I add any net new Skills rows vs the original? If yes → merge them back down
- Does any TCS bullet wrap to 3 lines in a typical PDF render? If yes → trim it
- Is the total line count equal to or less than the original? If no → fix it
- Does Education appear on page 1? If no → something above it is too long, find it
  and cut it

Only proceed to output after all 5 checks pass.

### STEP 6 — Output
Provide ONLY the complete, compilable LaTeX code — no explanation before or after.
The output should be ready to copy-paste directly into Overleaf or any LaTeX editor
and compile without errors on the first try.

---

## CONSTRAINTS SUMMARY (never violate these)
- Output = 1 page exactly — Education must appear on page 1
- Always delete `\vspace{2pt}` before the Summary section — this is a known
  template issue that causes page overflow regardless of content length
- Skills section = same row count as original or fewer, never more
- No fabricated experience, companies, degrees, or metrics
- No fabricated metrics — only reframe real ones with new keyword context
- Most recent job bullets are fair game for full rewrite
- All other job bullets = content locked, micro-trim only for space
- Inject keywords in priority order: Summary → Skills → Most Recent Job
- Every added keyword must appear naturally in a sentence, not as a standalone tag
- Final LaTeX must compile without errors
- If in doubt between adding a keyword and keeping 1 page — keep 1 page, always
"""


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


# Used when a generated document is structurally broken or fails to compile —
# one corrective pass with the concrete problem attached.
LATEX_REPAIR_PROMPT = r"""The following LaTeX resume is broken and does not compile.

PROBLEM:
{problem}

Return the corrected, COMPLETE LaTeX document — from \documentclass through
\end{document} — and nothing else (no commentary, no analysis, no markdown
fences). Keep the resume content identical; fix ONLY the structural/syntax
problems. Every piece of visible text must be between \begin{document} and
\end{document}.

LATEX SOURCE TO FIX:
{latex_source}"""


def build_repair_prompt(latex_source: str, problem: str) -> str:
    return (
        LATEX_REPAIR_PROMPT
        .replace("{problem}", problem or "It fails to compile.")
        .replace("{latex_source}", latex_source or "")
    )