"""Resume Versions — view and download every JD-tailored resume per job."""

from __future__ import annotations

import streamlit as st

import api_client as api
from theme import inject_theme, page_header

st.set_page_config(page_title="Resume Versions · job-auto-apply", page_icon="📄", layout="wide")
inject_theme()

page_header("Resume Versions", "Every resume the system has generated, per job.",
            eyebrow="Documents")
st.write("")

try:
    jobs = api.list_jobs(limit=2000)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not jobs:
    st.info("No jobs discovered yet — run **Discover jobs now** from the home page first.",
            icon="📄")
    st.stop()

job_by_id = {j["id"]: j for j in jobs}
job_id = st.selectbox(
    "Choose a job",
    options=list(job_by_id.keys()),
    format_func=lambda i: f"#{i} · {job_by_id[i]['title']} — {job_by_id[i]['company']}",
)

col1, col2 = st.columns(2)
with col1:
    if st.button("📄 Tailor a new resume (LLM)", width="stretch"):
        with st.spinner("Generating + compiling…"):
            try:
                res = api.tailor_resume(job_id, force_tailor=True)
                if res.get("compiled"):
                    st.success(f"Tailored + compiled — version #{res['resume_version_id']}.")
                else:
                    st.warning(
                        f"Generated LaTeX (version #{res['resume_version_id']}) but it "
                        "didn't compile — install `tectonic` or `pdflatex` for a PDF."
                    )
            except api.APIError as exc:
                st.error(str(exc))
with col2:
    if st.button("📎 Compile base resume", width="stretch",
                 help="Your untailored base resume — instant, no LLM"):
        with st.spinner("Compiling base resume…"):
            try:
                res = api.tailor_resume(job_id, force_tailor=False)
                st.success(f"Version #{res['resume_version_id']} ready.")
            except api.APIError as exc:
                st.error(str(exc))

st.divider()

try:
    versions = api.list_job_resumes(job_id)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not versions:
    st.info("No resume versions for this job yet — generate one above.", icon="📄")
    st.stop()

for v in versions:
    badge = "✅ compiled PDF" if v.get("compiled") else "⚠️ LaTeX only (compile failed)"
    with st.container(border=True):
        st.markdown(
            f'<span class="ja-meta">Version #{v["id"]} · {v["generated_at"]} · {badge}</span>',
            unsafe_allow_html=True,
        )
        cols = st.columns([1, 1, 3])
        if v.get("compiled"):
            try:
                pdf = api.resume_pdf_bytes(v["id"])
                cols[0].download_button("⬇ Download PDF", data=pdf,
                                        file_name=f"resume_v{v['id']}.pdf",
                                        mime="application/pdf", key=f"dl_{v['id']}",
                                        width="stretch")
            except api.APIError as exc:
                cols[0].warning(f"PDF unavailable: {exc}")
        if cols[1].button("👁 View LaTeX", key=f"tex_{v['id']}", width="stretch"):
            try:
                detail = api.get_resume_version(v["id"])
                st.code(detail.get("tex_content") or "(empty)", language="latex")
            except api.APIError as exc:
                st.error(str(exc))
