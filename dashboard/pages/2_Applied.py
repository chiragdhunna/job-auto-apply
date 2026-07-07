"""Applied — the applications you've marked as submitted.

Each row carries a pipeline-stage trail (discovered → scored (NN) → tailored →
applied) — a real sequence this job actually moved through, not decoration.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import api_client as api
from theme import (
    inject_theme,
    page_header,
    render_fit_score_bar,
    stage_trail,
    status_pill,
)

st.set_page_config(page_title="Applied · job-auto-apply", page_icon="▮", layout="wide")
inject_theme()

page_header("applied", cmd="history --applied --by=date",
            subtitle="Everything you've marked as submitted.")

try:
    apps = api.list_applications()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not apps:
    st.info(
        "Nothing applied yet. On the **recommended** page: open a posting, send "
        "your application, then hit **✓ I applied** — it lands here with its "
        "full pipeline trail.",
        icon="▮",
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

# --- Cards with the earned stage trail --------------------------------------- #
for _, row in view.head(50).iterrows():
    r = row.to_dict()
    fit = r.get("fit_score")
    with st.container(border=True):
        # Trail: real stages this job actually passed through, in real order.
        scored_label = f"scored ({fit:.0f})" if pd.notna(fit) and fit is not None else "scored"
        trail = stage_trail([
            ("discovered", True),
            (scored_label, pd.notna(fit) and fit is not None),
            ("tailored", bool(r.get("resume_version_id"))),
            ("applied", True),
        ])
        st.markdown(trail, unsafe_allow_html=True)
        left, right = st.columns([1.4, 5.6], gap="medium")
        with left:
            st.markdown(render_fit_score_bar(fit if pd.notna(fit) else None),
                        unsafe_allow_html=True)
        with right:
            when = r["submitted_at"].strftime("%Y-%m-%d") if pd.notna(r.get("submitted_at")) else "—"
            st.markdown(
                f'<span class="ja-title">{r.get("title")}</span> '
                f'<span class="ja-meta">·</span> <span class="ja-company">{r.get("company")}</span><br>'
                f'<span class="ja-meta">{when} · via {r.get("platform")}</span> '
                f'{status_pill(r.get("status", ""))}',
                unsafe_allow_html=True,
            )
            if r.get("platform_response_notes"):
                st.markdown(f'<span class="ja-reason">{r["platform_response_notes"]}</span>',
                            unsafe_allow_html=True)
            cols = st.columns([1.2, 4])
            if r.get("url"):
                cols[0].link_button("Open posting", r["url"], width="stretch")
            if r.get("custom_answers"):
                with st.expander("Answers you submitted"):
                    st.json(r["custom_answers"])
