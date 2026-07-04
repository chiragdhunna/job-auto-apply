"""Applied — history of submitted / attempted applications."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api

st.set_page_config(page_title="Applied · job-auto-apply", page_icon="📨", layout="wide")
st.title("📨 Applied")

try:
    apps = api.list_applications()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not apps:
    st.info("No applications yet. Once the automation modules submit applications, "
            "they'll appear here.")
    st.stop()

df = pd.DataFrame(apps)
if "submitted_at" in df.columns:
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")

# --- Filters --------------------------------------------------------------- #
c1, c2, c3 = st.columns(3)
platforms = sorted(p for p in df["platform"].dropna().unique())
statuses = sorted(s for s in df["status"].dropna().unique())
with c1:
    sel_platforms = st.multiselect("Platform", platforms, default=platforms)
with c2:
    sel_statuses = st.multiselect("Status", statuses, default=statuses)
with c3:
    date_range = st.date_input("Submitted between", value=())

mask = df["platform"].isin(sel_platforms) & df["status"].isin(sel_statuses)
if isinstance(date_range, tuple) and len(date_range) == 2 and df["submitted_at"].notna().any():
    start, end = date_range
    mask &= df["submitted_at"].dt.date.between(start, end)

view = df[mask].sort_values("submitted_at", ascending=False)

st.caption(f"{len(view)} application(s)")
st.dataframe(
    view[["id", "submitted_at", "platform", "company", "title", "status", "platform_response_notes"]],
    use_container_width=True,
    hide_index=True,
)

# --- Detail ---------------------------------------------------------------- #
st.divider()
ids = view["id"].tolist()
if ids:
    sel = st.selectbox("Inspect application", ids, format_func=lambda i: f"#{i}")
    row = df[df["id"] == sel].iloc[0].to_dict()
    st.write(f"**{row.get('title')}** at **{row.get('company')}** — {row.get('status')}")
    if row.get("url"):
        st.write(f"🔗 [posting]({row['url']})")
    answers = row.get("custom_answers")
    if answers:
        st.write("**Submitted answers:**")
        st.json(answers)
