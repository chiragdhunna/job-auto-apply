"""job-auto-apply dashboard — home / overview.

Run with:  streamlit run dashboard/app.py
(The backend must be running; set BACKEND_URL if it isn't on localhost:8000.)
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

import api_client as api

st.set_page_config(page_title="job-auto-apply", page_icon="🎯", layout="wide")

st.title("🎯 job-auto-apply")
st.caption("Local, automated job discovery → scoring → tailoring → application.")

# --- Backend health -------------------------------------------------------- #
try:
    api.health()
    backend_ok = True
except api.APIError as exc:
    backend_ok = False
    st.error(f"Backend unreachable. Start it with `uvicorn backend.main:app --port 8000`.\n\n{exc}")

if backend_ok:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Pipeline at a glance")
        try:
            jobs = api.list_jobs(limit=1000)
            counts = Counter(j["status"] for j in jobs)
            order = ["new", "scored", "queued", "applied", "failed", "skipped", "needs_review"]
            metric_cols = st.columns(len(order))
            for c, status in zip(metric_cols, order):
                c.metric(status.replace("_", " ").title(), counts.get(status, 0))
            st.metric("Total jobs discovered", len(jobs))
        except api.APIError as exc:
            st.warning(f"Could not load jobs: {exc}")

    with col2:
        st.subheader("LLM provider")
        try:
            status = api.llm_status()
            active = status.get("active_provider", "?")
            st.metric("Active provider", active.upper())
            gem = status.get("gemini", {})
            oll = status.get("ollama", {})
            st.write(f"**Gemini** — configured: {'✅' if gem.get('available') else '❌'} "
                     f"(`{gem.get('model')}`)")
            reach = oll.get("reachable")
            st.write(f"**Ollama** — reachable: {'✅' if reach else '❌'} "
                     f"(`{oll.get('model')}` @ `{oll.get('host')}`)")
            if active == "ollama" and not reach:
                st.warning("Active provider is Ollama but it is not reachable. "
                           "Run `ollama serve` and `ollama pull` a model.")
        except api.APIError as exc:
            st.warning(f"Could not load LLM status: {exc}")

    st.divider()
    st.subheader("Run the pipeline")
    b1, b2, _ = st.columns([1, 1, 3])
    with b1:
        if st.button("🔎 Scrape ATS boards now", use_container_width=True):
            with st.spinner("Scraping configured ATS boards…"):
                try:
                    st.success(f"Scrape complete: {api.scrape_now()['summary']}")
                except api.APIError as exc:
                    st.error(str(exc))
    with b2:
        if st.button("🧮 Score new jobs", use_container_width=True):
            with st.spinner("Scoring new jobs via the active LLM…"):
                try:
                    st.success(f"Scoring complete: {api.score_new()}")
                except api.APIError as exc:
                    st.error(str(exc))

    st.info("Use the pages in the sidebar: **Live Queue**, **Applied**, "
            "**Settings**, and **Resume Versions**.")
