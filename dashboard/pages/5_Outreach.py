"""Outreach — drafted recruiter messages you review and send YOURSELF.

This page never sends anything. Copy a draft (code blocks have a copy button),
open LinkedIn / your email client yourself, then record it with "I sent this".
"""

from __future__ import annotations

import urllib.parse

import streamlit as st

import api_client as api
from theme import inject_theme, page_header

st.set_page_config(page_title="Outreach · job-auto-apply", page_icon="✉️", layout="wide")
inject_theme()

page_header(
    "outreach",
    cmd="outreach --drafts --review-only",
    subtitle="Personalized drafts for recruiters & hiring managers. Draft-only: you review and send every message yourself.",
)

# --- Overview ---------------------------------------------------------------- #
try:
    rows = api.outreach_overview()
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

if not rows:
    st.info(
        "No recommended or applied jobs yet — outreach drafts attach to those. "
        "Discover + score jobs first (★ Recommended page), then come back here.",
        icon="✉️",
    )
    st.stop()

rows.sort(key=lambda r: (-(r.get("fit_score") or 0)))
label = {
    r["job_id"]: (
        f"#{r['job_id']} · {r['title']} — {r['company']}"
        f"  [{'contact ✓' if r['contact_found'] else 'no contact'} · "
        f"{r['drafts']} draft(s)]"
    )
    for r in rows
}
job_id = st.selectbox("Job", options=list(label.keys()), format_func=lambda i: label[i])

try:
    data = api.get_outreach(job_id)
except api.APIError as exc:
    st.error(str(exc))
    st.stop()

st.markdown(
    f'<span class="ja-title">{data["title"]}</span> · '
    f'<span class="ja-company">{data["company"]}</span> '
    f'<span class="ja-meta">· <a href="{data["url"]}" target="_blank">open posting</a></span>',
    unsafe_allow_html=True,
)

# --- Contact ------------------------------------------------------------------ #
contact = data.get("contact")
ccol, rcol = st.columns([3, 1])
with ccol:
    if contact and contact.get("name"):
        bits = [f"**{contact['name']}**"]
        if contact.get("title"):
            bits.append(contact["title"])
        bits.append(f"confidence: {contact['confidence']} · via {contact['source']}")
        st.markdown(" · ".join(bits))
        links = []
        if contact.get("linkedin_url"):
            links.append(f"[LinkedIn profile]({contact['linkedin_url']})")
        if contact.get("email"):
            links.append(f"`{contact['email']}`")
        if links:
            st.markdown(" · ".join(links))
    else:
        st.markdown(
            "**No contact identified** — nothing was fabricated. Drafts address "
            "the Hiring Team generically; add a real contact below if you find one, "
            "or send the general version."
        )
        if contact and (contact.get("email") or contact.get("linkedin_url")):
            extras = []
            if contact.get("email"):
                extras.append(f"recruiting inbox found: `{contact['email']}`")
            if contact.get("linkedin_url"):
                extras.append(f"[LinkedIn link found]({contact['linkedin_url']})")
            st.markdown(" · ".join(extras))
with rcol:
    if st.button("♻️ Regenerate drafts", width="stretch",
                 help="New contact lookup + fresh drafts (uses the LLM)"):
        with st.spinner("Identifying contact + drafting…"):
            try:
                api.regenerate_outreach(job_id)
                st.rerun()
            except api.APIError as exc:
                st.error(str(exc))

with st.expander("✏️ Add / correct the contact manually"):
    with st.form(f"contact_form_{job_id}"):
        n = st.text_input("Name", value=(contact or {}).get("name") or "")
        t = st.text_input("Title", value=(contact or {}).get("title") or "")
        lu = st.text_input("LinkedIn URL", value=(contact or {}).get("linkedin_url") or "")
        em = st.text_input("Email", value=(contact or {}).get("email") or "")
        if st.form_submit_button("Save contact"):
            try:
                api.set_outreach_contact(job_id, name=n or None, title=t or None,
                                         linkedin_url=lu or None, email=em or None)
                st.rerun()
            except api.APIError as exc:
                st.error(str(exc))

st.divider()

# --- Drafts -------------------------------------------------------------------- #
drafts = data.get("drafts") or []
if not drafts:
    st.info("No drafts yet for this job — click **Regenerate drafts** above to create "
            "the LinkedIn + email pair.", icon="📝")
    st.stop()

# newest first per channel
latest = {}
for d in drafts:
    latest.setdefault(d["channel"], d)

CHANNEL_META = {
    "linkedin_message": ("💬 LinkedIn message", "Short and specific — paste into LinkedIn yourself."),
    "email": ("📧 Email", "Opens YOUR email client via mailto — you press send."),
}

for channel, d in latest.items():
    title, hint = CHANNEL_META.get(channel, (channel, ""))
    with st.container(border=True):
        head = f"**{title}** · status: `{d['status']}`"
        if d.get("sent_at"):
            head += f" · sent {d['sent_at'][:10]}"
        st.markdown(head)
        if d["status"] == "needs_owner_input":
            st.warning(
                "Flagged: the draft either tripped the template-filler check or the "
                "JD was too thin for a specific hook. Edit in your own angle before "
                "sending — don't send it as-is.",
                icon="✋",
            )
        st.caption(hint)

        subject = None
        if channel == "email":
            subject = st.text_input("Subject", value=d.get("subject") or "", key=f"subj_{d['id']}")
        edited = st.text_area("Draft", value=d["draft_text"], height=160, key=f"text_{d['id']}",
                              label_visibility="collapsed")

        st.code(edited or d["draft_text"], language=None)  # native copy button

        cols = st.columns([1.2, 1.4, 1.2, 1, 1])
        with cols[0]:
            if st.button("💾 Save my edits", key=f"save_{d['id']}", width="stretch"):
                try:
                    api.save_outreach_draft(job_id, d["id"], edited, subject)
                    st.rerun()
                except api.APIError as exc:
                    st.error(str(exc))
        with cols[1]:
            if channel == "email":
                email_to = (contact or {}).get("email") or ""
                mailto = (
                    f"mailto:{urllib.parse.quote(email_to)}"
                    f"?subject={urllib.parse.quote(subject or d.get('subject') or '')}"
                    f"&body={urllib.parse.quote(edited or d['draft_text'])}"
                )
                st.link_button("📮 Compose in my email app", mailto, width="stretch",
                               help="Opens your own mail client pre-filled. Sending stays in your hands.")
            elif (contact or {}).get("linkedin_url"):
                st.link_button("👤 Open LinkedIn profile", contact["linkedin_url"], width="stretch")
        with cols[2]:
            if d["status"] != "sent" and st.button("✓ I sent this", key=f"sent_{d['id']}",
                                                    width="stretch",
                                                    help="Records that YOU sent it — status only"):
                try:
                    api.mark_draft_sent(job_id, d["id"])
                    st.rerun()
                except api.APIError as exc:
                    st.error(str(exc))
        with cols[3]:
            if d["status"] not in ("sent", "skipped") and st.button(
                    "Skip", key=f"skip_{d['id']}", width="stretch"):
                try:
                    api.skip_draft(job_id, d["id"])
                    st.rerun()
                except api.APIError as exc:
                    st.error(str(exc))

st.caption("By design there is no send button here — copy the draft, send it from your "
           "own LinkedIn/email, then record it. Automated cold outreach reads as spam; "
           "the drafting is automated, the judgment stays yours.")
