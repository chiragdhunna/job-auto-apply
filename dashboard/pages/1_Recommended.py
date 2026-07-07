"""Recommended — the jobs worth applying to next, best fit first.

Each row leads with the signature score chip (fit strength at a glance), then the
posting details, a link to apply, a one-click tailored resume, and a tick to
record that you've applied. The score chip's colour + band label encode 60-vs-95
as visual weight — the whole point of the tool.
"""

from __future__ import annotations

import streamlit as st

import api_client as api
from theme import inject_theme, page_header, render_fit_score_bar, status_pill

st.set_page_config(page_title="Recommended · jobctl", page_icon="▮", layout="wide")
inject_theme()

page_header(
    "recommended",
    cmd="recommended --sort=fit-score --desc",
    subtitle="Highest-fit first. Open the posting, grab your tailored resume, apply, tick it off.",
)

# --- Controls --------------------------------------------------------------- #
c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.4])
with c1:
    min_score = st.slider("Minimum fit score", 0, 100, 0, step=5,
                          help="Hide anything the LLM scored below this")
with c2:
    show_done = st.checkbox("Include applied / skipped", value=False)
with c3:
    limit = st.selectbox("Show top", [25, 50, 100, 200], index=1)
with c4:
    search = st.text_input("Search title or company", "", placeholder="e.g. backend, Stripe")

a, b, _ = st.columns([1, 1, 2])
with a:
    if st.button("🔎 Discover jobs now", width="stretch"):
        with st.spinner("Scraping every enabled source…"):
            try:
                st.success(api.scrape_now()["summary"])
            except api.APIError as exc:
                st.error(str(exc))
with b:
    if st.button("🧮 Score new jobs", width="stretch"):
        with st.spinner("Scoring via the active LLM (slow on Ollama)…"):
            try:
                st.success(api.score_new())
            except api.APIError as exc:
                st.error(str(exc))

# --- Data ------------------------------------------------------------------- #
try:
    jobs = api.get_recommended(min_score=min_score or None, include_done=show_done, limit=int(limit))
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if search.strip():
    q = search.lower()
    jobs = [j for j in jobs if q in (j["title"] or "").lower() or q in (j["company"] or "").lower()]

sources = sorted({j["source"] for j in jobs})
if sources:
    picked = st.multiselect("Sources", sources, default=sources)
    jobs = [j for j in jobs if j["source"] in picked]

# --- Empty state (an invitation to act, not a dead end) --------------------- #
if not jobs:
    st.info(
        "No jobs to show yet. Run `./discover.sh` in a terminal (one full "
        "discovery + scoring cycle), or trigger it here: **Discover jobs now** "
        "pulls fresh postings, **Score new jobs** ranks them. Anything at or "
        "above your threshold lands here. (Filtered everything out? Lower the "
        "minimum-score slider.)",
    )
    st.stop()

n_rec = sum(1 for j in jobs if j.get("recommended"))
st.caption(f"{len(jobs)} shown · {n_rec} at or above your recommend threshold")
st.write("")

RENDER_CAP = 60
for j in jobs[:RENDER_CAP]:
    with st.container(border=True):
        left, right = st.columns([1.4, 5.6], gap="medium")
        with left:
            # The signature element: same bar, same place, every page.
            st.markdown(render_fit_score_bar(j.get("fit_score")), unsafe_allow_html=True)
        with right:
            st.markdown(
                f'<span class="ja-title">{j["title"]}</span> '
                f'<span class="ja-meta">·</span> '
                f'<span class="ja-company">{j["company"]}</span>',
                unsafe_allow_html=True,
            )
            loc = j.get("location") or "location n/a"
            salary = f' · 💰 {j["salary_range"]}' if j.get("salary_range") else ""
            st.markdown(
                f'<span class="ja-meta">{loc} · via {j["source"]}{salary}</span> '
                f'{status_pill(j["status"])}',
                unsafe_allow_html=True,
            )
            details = j.get("score_details") or {}
            if details.get("reasoning"):
                st.markdown(f'<div class="ja-reason">{details["reasoning"]}</div>',
                            unsafe_allow_html=True)

            bcols = st.columns([1.1, 1.3, 1.2, 1.1, 0.9])
            with bcols[0]:
                st.link_button("🔗 Open posting", j["url"] or "#", width="stretch")
            with bcols[1]:
                if st.button("📄 Tailor resume", key=f"tailor_{j['id']}", width="stretch",
                             help="LLM-tailored to this JD (slow on Ollama, seconds on Gemini)"):
                    with st.spinner("Tailoring resume to this job…"):
                        try:
                            res = api.tailor_resume(j["id"], force_tailor=True)
                            st.session_state[f"rv_{j['id']}"] = res.get("resume_version_id")
                            if not res.get("compiled"):
                                st.warning("Generated the LaTeX, but PDF compile failed — "
                                           "check that tectonic/pdflatex is installed.")
                        except api.APIError as exc:
                            st.error(str(exc))
            with bcols[2]:
                if st.button("📎 Quick resume", key=f"quick_{j['id']}", width="stretch",
                             help="Instant: compiles your base resume, no LLM"):
                    with st.spinner("Compiling base resume…"):
                        try:
                            res = api.tailor_resume(j["id"], force_tailor=False)
                            st.session_state[f"rv_{j['id']}"] = res.get("resume_version_id")
                        except api.APIError as exc:
                            st.error(str(exc))
            with bcols[3]:
                if j["status"] == "applied":
                    if st.button("↩ Not applied", key=f"undo_{j['id']}", width="stretch"):
                        try:
                            api.unmark_applied(j["id"]); st.rerun()
                        except api.APIError as exc:
                            st.error(str(exc))
                elif st.button("✓ I applied", key=f"applied_{j['id']}", width="stretch",
                               help="Record that you submitted this application"):
                    try:
                        api.mark_applied(j["id"]); st.rerun()
                    except api.APIError as exc:
                        st.error(str(exc))
            with bcols[4]:
                if j["status"] != "applied" and st.button("Skip this job", key=f"skip_{j['id']}",
                                                           width="stretch", help="Hide it from the list"):
                    try:
                        api.set_job_status(j["id"], "skipped"); st.rerun()
                    except api.APIError as exc:
                        st.error(str(exc))

            if details.get("matched_skills") or details.get("gaps"):
                with st.expander("Why this score"):
                    if details.get("matched_skills"):
                        st.markdown("**You match:** " + ", ".join(details["matched_skills"][:12]))
                    if details.get("gaps"):
                        st.markdown("**Gaps to address:** " + ", ".join(details["gaps"][:8]))

            rv_id = st.session_state.get(f"rv_{j['id']}")
            if rv_id is None:
                try:
                    compiled = [v for v in api.list_job_resumes(j["id"]) if v.get("compiled")]
                    if compiled:
                        rv_id = compiled[0]["id"]
                except api.APIError:
                    rv_id = None
            if rv_id:
                try:
                    pdf = api.resume_pdf_bytes(rv_id)
                    st.download_button(
                        "⬇ Download resume PDF", data=pdf,
                        file_name=f"{(j['company'] or 'resume').replace(' ', '_')}_{j['id']}.pdf",
                        mime="application/pdf", key=f"dl_{j['id']}_{rv_id}",
                    )
                except api.APIError:
                    pass

if len(jobs) > RENDER_CAP:
    st.caption(f"Showing the top {RENDER_CAP}. Narrow with search or a higher minimum score.")
