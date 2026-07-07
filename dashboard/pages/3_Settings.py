"""Settings — edit runtime config (threshold, platforms, interval) + LLM status."""

from __future__ import annotations

import streamlit as st

import api_client as api

st.set_page_config(page_title="Settings · job-auto-apply", page_icon="⚙️", layout="wide")
st.title("⚙️ Settings")

try:
    settings = api.get_settings()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

# --- LLM status ------------------------------------------------------------ #
st.subheader("LLM provider")
try:
    status = api.llm_status()
    c1, c2, c3 = st.columns(3)
    c1.metric("Active provider", status.get("active_provider", "?").upper())
    gem = status.get("gemini", {})
    oll = status.get("ollama", {})
    c2.metric("Gemini configured", "Yes" if gem.get("available") else "No")
    c3.metric("Ollama reachable", "Yes" if oll.get("reachable") else "No")
    st.caption(
        f"Setting: `{status.get('provider_setting')}` · "
        f"Gemini model `{gem.get('model')}` · "
        f"Ollama `{oll.get('model')}` @ `{oll.get('host')}`"
    )
    if status.get("active_provider") == "ollama" and not oll.get("reachable"):
        st.warning("Ollama is the active provider but is not reachable. "
                   "Start it (`ollama serve`) and pull a model, or set GEMINI_API_KEY.")
except api.APIError as exc:
    st.warning(f"Could not load LLM status: {exc}")

st.divider()

# --- Editable settings ----------------------------------------------------- #
st.subheader("Pipeline settings")
with st.form("settings_form"):
    threshold = st.slider(
        "Score threshold (⭐ recommended at or above)",
        min_value=0, max_value=100, value=int(settings.get("score_threshold", 70)),
    )
    interval = st.number_input(
        "Scheduler run interval (minutes)",
        min_value=1, value=int(settings.get("run_interval_minutes", 60)),
    )
    st.markdown("**Discovery sources** (which places jobs are pulled from)")
    toggles = dict(settings.get("platform_toggles", {}))
    new_toggles = {}
    cols = st.columns(len(toggles) or 1)
    for col, (platform, enabled) in zip(cols, toggles.items()):
        new_toggles[platform] = col.checkbox(platform, value=bool(enabled))

    submitted = st.form_submit_button("💾 Save settings")
    if submitted:
        try:
            updated = api.update_settings(
                {
                    "score_threshold": int(threshold),
                    "run_interval_minutes": int(interval),
                    "platform_toggles": new_toggles,
                }
            )
            st.success("Saved.")
            st.json(
                {k: v for k, v in updated.items()
                 if k in ("score_threshold", "run_interval_minutes", "platform_toggles")}
            )
        except api.APIError as exc:
            st.error(str(exc))

st.divider()
st.subheader("Manual runs")
c1, c2 = st.columns(2)
if c1.button("🔎 Scrape ATS boards now", use_container_width=True):
    with st.spinner("Scraping…"):
        try:
            st.success(api.scrape_now()["summary"])
        except api.APIError as exc:
            st.error(str(exc))
if c2.button("🧮 Score new jobs", use_container_width=True):
    with st.spinner("Scoring…"):
        try:
            st.success(api.score_new())
        except api.APIError as exc:
            st.error(str(exc))

st.caption("Note: target roles, locations and target companies live in "
           "`config/keywords.yaml` (edit that file and restart).")

st.divider()

# --- Danger zone ------------------------------------------------------------ #
with st.expander("🗑️ Danger zone — clear the database"):
    st.warning(
        "This permanently deletes **all discovered jobs, your applied history, "
        "and all resume versions**. The next scheduler cycle starts discovery "
        "from scratch. This cannot be undone."
    )
    del_files = st.checkbox("Also delete the generated resume PDF files (data/resumes/)", value=True)
    reset_settings = st.checkbox(
        "Also reset these settings (threshold / toggles / interval) to keywords.yaml defaults",
        value=False,
    )
    confirm_text = st.text_input('Type DELETE to confirm', key="clear_confirm")
    if st.button("🗑️ Clear database now", type="primary", disabled=(confirm_text != "DELETE")):
        try:
            result = api.clear_data(delete_resume_files=del_files, include_settings=reset_settings)
            st.success(
                f"Cleared: {result.get('jobs', 0)} jobs, "
                f"{result.get('applications', 0)} applications, "
                f"{result.get('resume_versions', 0)} resume versions, "
                f"{result.get('resume_files', 0)} PDF files"
                + (f", {result.get('settings', 0)} settings" if reset_settings else "")
                + ". Fresh start!"
            )
        except api.APIError as exc:
            st.error(str(exc))
