"""Live Queue — review discovered/scored/queued jobs and take action."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api

st.set_page_config(page_title="Live Queue · job-auto-apply", page_icon="📋", layout="wide")
st.title("📋 Live Queue")

ALL_STATUSES = ["new", "scored", "queued", "needs_review", "applied", "failed", "skipped"]

statuses = st.multiselect(
    "Show statuses",
    ALL_STATUSES,
    default=["new", "scored", "queued", "needs_review"],
)
col_a, col_b = st.columns([1, 1])
with col_a:
    if st.button("🔎 Scrape now"):
        with st.spinner("Scraping…"):
            try:
                st.success(api.scrape_now()["summary"])
            except api.APIError as exc:
                st.error(str(exc))
with col_b:
    if st.button("🧮 Score new jobs"):
        with st.spinner("Scoring…"):
            try:
                st.success(api.score_new())
            except api.APIError as exc:
                st.error(str(exc))

try:
    all_jobs = api.list_jobs(limit=1000)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

jobs = [j for j in all_jobs if j["status"] in statuses] if statuses else all_jobs
jobs.sort(key=lambda j: (j.get("fit_score") is None, -(j.get("fit_score") or 0)))

st.caption(f"{len(jobs)} job(s) shown")

if jobs:
    df = pd.DataFrame(
        [
            {
                "id": j["id"],
                "score": j.get("fit_score"),
                "status": j["status"],
                "title": j["title"],
                "company": j["company"],
                "location": j.get("location"),
                "source": j["source"],
            }
            for j in jobs
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Actions")

for j in jobs[:60]:
    score = j.get("fit_score")
    score_txt = f"{score:.0f}" if score is not None else "—"
    header = f"[{score_txt}] {j['title']} · {j['company']} ({j['source']}) — {j['status']}"
    with st.expander(header):
        st.write(f"📍 {j.get('location') or 'N/A'}  ·  🔗 [posting]({j['url']})")
        details = j.get("score_details")
        if details:
            if details.get("reasoning"):
                st.write(f"**Reasoning:** {details['reasoning']}")
            if details.get("matched_skills"):
                st.write("**Matched:** " + ", ".join(details["matched_skills"]))
            if details.get("gaps"):
                st.write("**Gaps:** " + ", ".join(details["gaps"]))

        c1, c2, c3, c4, c5 = st.columns(5)
        if c1.button("✅ Approve", key=f"approve_{j['id']}", help="Move to queued"):
            try:
                api.set_job_status(j["id"], "queued")
                st.rerun()
            except api.APIError as exc:
                st.error(str(exc))
        if c2.button("⏭️ Skip", key=f"skip_{j['id']}"):
            try:
                api.set_job_status(j["id"], "skipped")
                st.rerun()
            except api.APIError as exc:
                st.error(str(exc))
        if c3.button("🧮 Score", key=f"score_{j['id']}"):
            with st.spinner("Scoring…"):
                try:
                    st.success(api.score_job(j["id"]))
                    st.rerun()
                except api.APIError as exc:
                    st.error(str(exc))
        if c4.button("📄 Resume", key=f"resume_{j['id']}", help="Generate a tailored resume"):
            with st.spinner("Tailoring resume…"):
                try:
                    st.success(api.tailor_resume(j["id"]))
                except api.APIError as exc:
                    st.error(str(exc))
        if c5.button("💬 Answers", key=f"ans_{j['id']}", help="Preview common answers"):
            with st.spinner("Generating answers…"):
                try:
                    st.json(api.generate_answers(j["id"])["answers"])
                except api.APIError as exc:
                    st.error(str(exc))
