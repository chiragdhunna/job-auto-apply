"""job-auto-apply dashboard — home / command center.

Run with:  streamlit run dashboard/app.py
(The backend must be running; set BACKEND_URL if it isn't on localhost:8000.)
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

import api_client as api
from theme import inject_theme, page_header

st.set_page_config(page_title="job-auto-apply", page_icon="▮", layout="wide")
inject_theme()

page_header(
    "overview",
    cmd="pipeline status && llm status",
    subtitle="Discover roles everywhere, score them against your resume, act on the best fits fast.",
)

# --- Backend health -------------------------------------------------------- #
try:
    api.health()
    backend_ok = True
except api.APIError as exc:
    backend_ok = False
    st.error(
        "Can't reach the backend. Start it with "
        "`uvicorn backend.main:app --port 8000` (or run `./run.sh`).\n\n"
        f"{exc}"
    )

if backend_ok:
    col1, col2 = st.columns([2, 1], gap="large")

    with col1:
        st.markdown("#### Your pipeline")
        try:
            jobs = api.list_jobs(limit=2000)
            counts = Counter(j["status"] for j in jobs)
            scored = [j for j in jobs if j.get("fit_score") is not None]
            strong = sum(1 for j in scored if (j["fit_score"] or 0) >= 85)

            m = st.columns(4)
            m[0].metric("Discovered", len(jobs))
            m[1].metric("★ Recommended", counts.get("queued", 0))
            m[2].metric("Applied", counts.get("applied", 0))
            m[3].metric("Strong fits (85+)", strong)
            st.caption(
                f"{counts.get('scored', 0) + counts.get('queued', 0)} scored · "
                f"{counts.get('new', 0)} awaiting scoring · "
                f"{counts.get('skipped', 0)} skipped"
            )
        except api.APIError as exc:
            st.warning(f"Couldn't load jobs: {exc}")

    with col2:
        st.markdown("#### LLM engine")
        try:
            status = api.llm_status()
            active = status.get("active_provider", "?")
            st.metric("Active provider", active.upper())
            gem, oll = status.get("gemini", {}), status.get("ollama", {})
            st.markdown(
                f"**Gemini** — {'✅ configured' if gem.get('available') else '❌ not configured'} "
                f"(`{gem.get('model')}`)"
            )
            reach = oll.get("reachable")
            st.markdown(
                f"**Ollama** — {'✅ reachable' if reach else '❌ unreachable'} "
                f"(`{oll.get('model')}`)"
            )
            if active == "ollama" and not reach:
                st.warning(
                    "Active provider is Ollama but it's not reachable — run "
                    "`ollama serve` and pull a model, or set GEMINI_API_KEY."
                )
        except api.APIError as exc:
            st.warning(f"Couldn't load LLM status: {exc}")

    st.divider()
    st.markdown("#### Refresh the pipeline")
    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if st.button("🔎 Discover jobs now", width="stretch",
                     help="Scrape every enabled ATS + web source"):
            with st.spinner("Scraping ATS boards + web job boards…"):
                try:
                    st.success(f"Discovery complete: {api.scrape_now()['summary']}")
                except api.APIError as exc:
                    st.error(str(exc))
    with b2:
        if st.button("🧮 Score new jobs", width="stretch",
                     help="Rank every unscored job with the active LLM"):
            with st.spinner("Scoring via the active LLM…"):
                try:
                    st.success(f"Scoring complete: {api.score_new()}")
                except api.APIError as exc:
                    st.error(str(exc))

    st.info(
        "Open **★ Recommended** in the sidebar — best-fit jobs first, with a link "
        "to each posting, a one-click tailored resume, and a tick to mark what "
        "you've applied to.",
        icon="🧭",
    )
