"""Recommended — the jobs worth applying to next, best fit first.

For each job: fit score + reasoning, a link to the actual posting, a one-click
JD-tailored resume (download it, then apply yourself), and a "Mark applied"
tick so the system tracks what you've already done.
"""

from __future__ import annotations

import streamlit as st

import api_client as api

st.set_page_config(page_title="Recommended · job-auto-apply", page_icon="⭐", layout="wide")
st.title("⭐ Recommended jobs")
st.caption("Highest-fit first. Open the posting, grab your tailored resume, apply, tick it off.")

# --- Controls --------------------------------------------------------------- #
c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.4])
with c1:
    min_score = st.slider("Minimum fit score", 0, 100, 0, step=5)
with c2:
    show_done = st.checkbox("Show applied/skipped", value=False)
with c3:
    limit = st.selectbox("Show top", [25, 50, 100, 200], index=1)
with c4:
    search = st.text_input("Search title/company", "")

ca, cb = st.columns([1, 1])
with ca:
    if st.button("🔎 Discover new jobs now", use_container_width=True):
        with st.spinner("Scraping ATS boards + web job boards…"):
            try:
                st.success(api.scrape_now()["summary"])
            except api.APIError as exc:
                st.error(str(exc))
with cb:
    if st.button("🧮 Score unscored jobs", use_container_width=True):
        with st.spinner("Scoring via the active LLM (slow on Ollama)…"):
            try:
                st.success(api.score_new())
            except api.APIError as exc:
                st.error(str(exc))

# --- Data ------------------------------------------------------------------- #
try:
    jobs = api.get_recommended(
        min_score=min_score or None, include_done=show_done, limit=int(limit)
    )
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

n_rec = sum(1 for j in jobs if j.get("recommended"))
st.caption(f"{len(jobs)} job(s) shown — {n_rec} above your threshold")

STATUS_BADGE = {"applied": "✅ applied", "skipped": "⏭ skipped", "queued": "", "scored": "", "needs_review": ""}

# --- Job cards --------------------------------------------------------------- #
for j in jobs:
    score = j.get("fit_score")
    star = "⭐ " if j.get("recommended") else ""
    badge = STATUS_BADGE.get(j["status"], "")
    header = (
        f"{star}{score:.0f} · {j['title']} — {j['company']}"
        f" · {(j.get('location') or 'location n/a')[:40]}"
        f" · {j['source']} {badge}"
    )
    with st.expander(header):
        details = j.get("score_details") or {}
        if details.get("reasoning"):
            st.write(f"**Why this fits:** {details['reasoning']}")
        mcol, gcol = st.columns(2)
        if details.get("matched_skills"):
            mcol.write("**You match:** " + ", ".join(details["matched_skills"][:10]))
        if details.get("gaps"):
            gcol.write("**Gaps:** " + ", ".join(details["gaps"][:6]))
        if j.get("salary_range"):
            st.write(f"💰 {j['salary_range']}")

        b1, b2, b3, b4, b5 = st.columns([1.2, 1.3, 1.3, 1, 1])
        with b1:
            st.link_button("🔗 Open posting", j["url"], use_container_width=True)
        with b2:
            if st.button("📄 Tailored resume", key=f"tailor_{j['id']}",
                         help="LLM-tailored to this JD (slow on Ollama, fast on Gemini)",
                         use_container_width=True):
                with st.spinner("Tailoring resume to this JD…"):
                    try:
                        res = api.tailor_resume(j["id"], force_tailor=True)
                        st.session_state[f"rv_{j['id']}"] = res.get("resume_version_id")
                        if not res.get("compiled"):
                            st.warning("Generated but PDF compile failed — check logs.")
                    except api.APIError as exc:
                        st.error(str(exc))
        with b3:
            if st.button("📎 Quick resume", key=f"quick_{j['id']}",
                         help="Instant: compiles your base resume for this job",
                         use_container_width=True):
                with st.spinner("Compiling base resume…"):
                    try:
                        res = api.tailor_resume(j["id"], force_tailor=False)
                        st.session_state[f"rv_{j['id']}"] = res.get("resume_version_id")
                    except api.APIError as exc:
                        st.error(str(exc))
        with b4:
            if j["status"] == "applied":
                if st.button("↩️ Undo", key=f"undo_{j['id']}", use_container_width=True):
                    try:
                        api.unmark_applied(j["id"])
                        st.rerun()
                    except api.APIError as exc:
                        st.error(str(exc))
            else:
                if st.button("✅ Mark applied", key=f"applied_{j['id']}", use_container_width=True):
                    try:
                        api.mark_applied(j["id"])
                        st.rerun()
                    except api.APIError as exc:
                        st.error(str(exc))
        with b5:
            if j["status"] != "applied" and st.button("⏭ Skip", key=f"skip_{j['id']}", use_container_width=True):
                try:
                    api.set_job_status(j["id"], "skipped")
                    st.rerun()
                except api.APIError as exc:
                    st.error(str(exc))

        # Offer the newest PDF for download (from this session's generation or history).
        rv_id = st.session_state.get(f"rv_{j['id']}")
        if rv_id is None:
            try:
                versions = api.list_job_resumes(j["id"])
                compiled = [v for v in versions if v.get("compiled")]
                if compiled:
                    rv_id = compiled[0]["id"]
            except api.APIError:
                rv_id = None
        if rv_id:
            try:
                pdf = api.resume_pdf_bytes(rv_id)
                st.download_button(
                    "⬇️ Download resume PDF",
                    data=pdf,
                    file_name=f"{(j['company'] or 'resume').replace(' ', '_')}_{j['id']}.pdf",
                    mime="application/pdf",
                    key=f"dl_{j['id']}_{rv_id}",
                )
            except api.APIError:
                pass
