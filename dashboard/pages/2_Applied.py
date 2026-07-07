"""Applied — the applications you've marked as submitted."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
from theme import inject_theme, page_header, status_pill

st.set_page_config(page_title="Applied · job-auto-apply", page_icon="📨", layout="wide")
inject_theme()

page_header("Applied", "Everything you've marked as submitted.", eyebrow="History")
st.write("")

try:
    apps = api.list_applications()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not apps:
    st.info(
        "No applications tracked yet. On the **★ Recommended** page, apply to a "
        "job and hit **✓ I applied** — it'll appear here with the resume version "
        "you used.",
        icon="📨",
    )
    st.stop()

df = pd.DataFrame(apps)
if "submitted_at" in df.columns:
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")

m = st.columns(3)
m[0].metric("Total applied", len(df))
m[1].metric("Companies", df["company"].nunique())
m[2].metric("Sources used", df["platform"].nunique())
st.write("")

# --- Filters ---------------------------------------------------------------- #
c1, c2, c3 = st.columns(3)
platforms = sorted(p for p in df["platform"].dropna().unique())
statuses = sorted(s for s in df["status"].dropna().unique())
with c1:
    sel_platforms = st.multiselect("Source", platforms, default=platforms)
with c2:
    sel_statuses = st.multiselect("Status", statuses, default=statuses)
with c3:
    date_range = st.date_input("Applied between", value=())

mask = df["platform"].isin(sel_platforms) & df["status"].isin(sel_statuses)
if isinstance(date_range, tuple) and len(date_range) == 2 and df["submitted_at"].notna().any():
    start, end = date_range
    mask &= df["submitted_at"].dt.date.between(start, end)

view = df[mask].sort_values("submitted_at", ascending=False)
st.caption(f"{len(view)} application(s)")
st.dataframe(
    view[["id", "submitted_at", "platform", "company", "title", "status", "platform_response_notes"]],
    width="stretch",
    hide_index=True,
    column_config={
        "id": st.column_config.NumberColumn("ID", width="small"),
        "submitted_at": st.column_config.DatetimeColumn("Applied", format="MMM D, YYYY"),
        "platform": "Source",
        "platform_response_notes": "Notes",
    },
)

# --- Detail ----------------------------------------------------------------- #
st.divider()
ids = view["id"].tolist()
if ids:
    sel = st.selectbox("Inspect an application", ids, format_func=lambda i: f"#{i}")
    row = df[df["id"] == sel].iloc[0].to_dict()
    st.markdown(
        f'<span class="ja-title">{row.get("title")}</span> · '
        f'<span class="ja-company">{row.get("company")}</span> '
        f'{status_pill(row.get("status", ""))}',
        unsafe_allow_html=True,
    )
    if row.get("url"):
        st.markdown(f'<span class="ja-meta">🔗 <a href="{row["url"]}" target="_blank">{row["url"]}</a></span>',
                    unsafe_allow_html=True)
    answers = row.get("custom_answers")
    if answers:
        st.markdown("**Answers you submitted:**")
        st.json(answers)
