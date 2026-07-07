"""Outreach message prompt templates. DRAFT-ONLY feature — messages are never sent.

Same pattern as backend/resume_tailor/prompts.py: paste your own prompt into
OWNER_OUTREACH_PROMPT to override; the default below is used otherwise.
Placeholders (substituted via str.replace, so braces in your text are safe):
    {job_title} {company} {job_description} {candidate_json}
    {contact_line}   -> "Priya Sharma, Talent Partner" or "the Hiring Team"
    {applied_line}   -> sentence noting an application was already submitted, or ""
"""

# ============================================================================
# PASTE OWNER'S OUTREACH PROMPT HERE (leave "" to use the default below)
# ============================================================================
OWNER_OUTREACH_PROMPT = ""


DEFAULT_OUTREACH_PROMPT = """You are drafting cold-outreach messages for a job candidate. The candidate
will review, edit, and send these THEMSELVES — write drafts worth their name.

CANDIDATE (JSON):
{candidate_json}

ROLE
Title: {job_title}
Company: {company}
Addressed to: {contact_line}
{applied_line}
Job description:
\"\"\"
{job_description}
\"\"\"

Write TWO drafts:

1. "linkedin_message" — max ~600 characters. Openers must earn attention in one
   line. Reference ONE concrete, specific thing from this JD or company (a
   named system, product, tech choice, team mission — something a template
   could not contain), connect it to ONE genuinely relevant thing from the
   candidate's real background, and close with a low-pressure ask ("happy to
   share more context if useful" energy — never "please refer me").

2. "email_subject" + "email_body" — a short email (under 150 words). Same
   personalization bar. If an application was already submitted, mention it
   naturally in one clause.

HARD BANS — never use these or anything like them:
- "I hope this message finds you well" / "I hope you're doing well"
- "I am writing to express my interest"
- "I came across your job posting"
- "Dear Sir or Madam" / "To Whom It May Concern"
- Any sentence that could be pasted into a different company's message unchanged.

Honesty rule: if this JD is too thin to say anything specific (no distinct
details), do NOT pad with filler — set "has_specific_hook" to false so the
candidate knows to add their own angle.

Return ONLY this JSON:
{"linkedin_message": "...", "email_subject": "...", "email_body": "...",
 "has_specific_hook": true/false}"""


def build_outreach_prompt(
    job_title: str,
    company: str,
    job_description: str,
    candidate_json: str,
    contact_line: str,
    applied_line: str,
) -> str:
    template = (OWNER_OUTREACH_PROMPT or "").strip() or DEFAULT_OUTREACH_PROMPT
    return (
        template
        .replace("{job_title}", job_title or "")
        .replace("{company}", company or "")
        .replace("{job_description}", job_description or "")
        .replace("{candidate_json}", candidate_json or "{}")
        .replace("{contact_line}", contact_line or "the Hiring Team")
        .replace("{applied_line}", applied_line or "")
    )
