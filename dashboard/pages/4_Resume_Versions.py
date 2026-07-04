"""Resume Versions — view / download JD-tailored resumes per job."""

from __future__ import annotations

import streamlit as st

import api_client as api

st.set_page_config(page_title="Resume Versions · job-auto-apply", page_icon="📄", layout="wide")
st.title("📄 Resume Versions")

try:
    jobs = api.list_jobs(limit=1000)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not jobs:
    st.info("No jobs yet — scrape some first.")
    st.stop()

job_by_id = {j["id"]: j for j in jobs}
job_id = st.selectbox(
    "Select a job",
    options=list(job_by_id.keys()),
    format_func=lambda i: f"#{i} · {job_by_id[i]['title']} — {job_by_id[i]['company']}",
)

if st.button("📄 Generate a tailored resume for this job"):
    with st.spinner("Generating + compiling…"):
        try:
            res = api.tailor_resume(job_id)
            if res.get("compiled"):
                st.success(f"Generated and compiled (resume version #{res['resume_version_id']}).")
            else:
                st.warning(
                    f"Generated LaTeX (resume version #{res['resume_version_id']}) but it was "
                    "not compiled — install `tectonic` or `pdflatex` to produce a PDF."
                )
        except api.APIError as exc:
            st.error(str(exc))

st.divider()

try:
    versions = api.list_job_resumes(job_id)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not versions:
    st.info("No resume versions for this job yet.")
    st.stop()

for v in versions:
    with st.expander(
        f"Version #{v['id']} · {v['generated_at']} · "
        f"{'✅ compiled' if v.get('compiled') else '⚠️ tex only'}"
    ):
        if v.get("compiled"):
            try:
                pdf = api.resume_pdf_bytes(v["id"])
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf,
                    file_name=f"resume_v{v['id']}.pdf",
                    mime="application/pdf",
                    key=f"dl_{v['id']}",
                )
            except api.APIError as exc:
                st.warning(f"PDF unavailable: {exc}")
        if st.button("👁️ View LaTeX source", key=f"tex_{v['id']}"):
            try:
                detail = api.get_resume_version(v["id"])
                st.code(detail.get("tex_content") or "(empty)", language="latex")
            except api.APIError as exc:
                st.error(str(exc))
