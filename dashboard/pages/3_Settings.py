"""Settings — tune scoring, discovery sources, and cadence; watch the LLM engine."""

from __future__ import annotations

import streamlit as st

import api_client as api
from theme import config_comment, inject_theme, page_header

st.set_page_config(page_title="Settings · jobctl", page_icon="⚙️", layout="wide")
inject_theme()

page_header("settings", cmd="cat keywords.yaml --editable",
            subtitle="What gets discovered, what counts as a strong fit, how often it runs.")

try:
    settings = api.get_settings()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

# --- LLM engine status ------------------------------------------------------ #
config_comment("llm engine")
try:
    status = api.llm_status()
    c1, c2, c3 = st.columns(3)
    c1.metric("Active provider", status.get("active_provider", "?").upper())
    gem, oll = status.get("gemini", {}), status.get("ollama", {})
    c2.metric("Gemini", "Configured" if gem.get("available") else "Not set")
    c3.metric("Ollama", "Reachable" if oll.get("reachable") else "Unreachable")
    st.caption(
        f"Setting `{status.get('provider_setting')}` · Gemini `{gem.get('model')}` · "
        f"Ollama `{oll.get('model')}` @ `{oll.get('host')}`"
    )
    if status.get("active_provider") == "ollama" and not oll.get("reachable"):
        st.warning("Ollama is active but unreachable — run `ollama serve` and pull a "
                   "model, or set GEMINI_API_KEY for faster scoring/tailoring.")
except api.APIError as exc:
    st.warning(f"Couldn't load LLM status: {exc}")

st.divider()

# --- Editable settings ------------------------------------------------------ #
config_comment("scoring")
with st.form("settings_form"):
    threshold = st.slider(
        "Recommend threshold — score at or above this shows as ★ Recommended",
        min_value=0, max_value=100, value=int(settings.get("score_threshold", 70)),
    )
    interval = st.number_input(
        "Scheduler cadence (minutes between discovery + scoring runs)",
        min_value=1, value=int(settings.get("run_interval_minutes", 60)),
    )

    st.markdown("**browser sources** — need a logged-in session; discovery only")
    platform_toggles = dict(settings.get("platform_toggles", {}))
    browser_keys = [k for k in ("linkedin", "indeed") if k in platform_toggles]
    ats_keys = [k for k in ("greenhouse", "lever", "ashby", "workday") if k in platform_toggles]
    new_platform = dict(platform_toggles)
    if browser_keys:
        cols = st.columns(len(browser_keys))
        for col, k in zip(cols, browser_keys):
            new_platform[k] = col.checkbox(k.title(), value=bool(platform_toggles[k]))

    st.markdown("**company ats sources** — public APIs")
    if ats_keys:
        cols = st.columns(len(ats_keys))
        for col, k in zip(cols, ats_keys):
            new_platform[k] = col.checkbox(k.title(), value=bool(platform_toggles[k]))

    st.markdown("**web job boards & aggregators**")
    source_toggles = dict(settings.get("source_toggles", {}))
    new_sources = dict(source_toggles)
    keys = sorted(source_toggles.keys())
    per_row = 4
    for i in range(0, len(keys), per_row):
        cols = st.columns(per_row)
        for col, k in zip(cols, keys[i:i + per_row]):
            new_sources[k] = col.checkbox(k, value=bool(source_toggles[k]), key=f"src_{k}")

    if st.form_submit_button("💾 Save settings", type="primary"):
        try:
            api.update_settings({
                "score_threshold": int(threshold),
                "run_interval_minutes": int(interval),
                "platform_toggles": new_platform,
                "source_toggles": new_sources,
            })
            st.success("Saved. Changes take effect on the next scheduler run.")
        except api.APIError as exc:
            st.error(str(exc))

st.divider()

config_comment("run manually")
c1, c2 = st.columns(2)
if c1.button("🔎 Discover jobs now", width="stretch"):
    with st.spinner("Scraping every enabled source…"):
        try:
            st.success(api.scrape_now()["summary"])
        except api.APIError as exc:
            st.error(str(exc))
if c2.button("🧮 Score new jobs", width="stretch"):
    with st.spinner("Scoring…"):
        try:
            st.success(api.score_new())
        except api.APIError as exc:
            st.error(str(exc))

st.caption("Target roles, locations and company slugs live in `config/keywords.yaml` "
           "(edit that file and restart to change them).")

st.divider()

# --- Danger zone ------------------------------------------------------------ #
config_comment("danger zone")
with st.expander("Clear the database"):
    st.warning(
        "Permanently deletes **all discovered jobs, your applied history, and all "
        "resume versions**. The next run starts discovery from scratch. No undo.",
        icon="⚠️",
    )
    del_files = st.checkbox("Also delete generated resume PDF files (data/resumes/)", value=True)
    reset_settings = st.checkbox(
        "Also reset these settings to keywords.yaml defaults", value=False)
    confirm_text = st.text_input("Type DELETE to confirm", key="clear_confirm")
    if st.button("Clear database now", type="primary", disabled=(confirm_text != "DELETE")):
        try:
            r = api.clear_data(delete_resume_files=del_files, include_settings=reset_settings)
            st.success(
                f"Cleared {r.get('jobs', 0)} jobs, {r.get('applications', 0)} applications, "
                f"{r.get('resume_versions', 0)} resume versions, {r.get('resume_files', 0)} PDFs"
                + (f", {r.get('settings', 0)} settings" if reset_settings else "") + "."
            )
        except api.APIError as exc:
            st.error(str(exc))
