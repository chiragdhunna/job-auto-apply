"""Design system for the jobctl dashboard — TERMINAL / AMBER.

═══════════════════════════════════════════════════════════════════════════════
DESIGN TOKENS (single source of truth — every page imports from here)
═══════════════════════════════════════════════════════════════════════════════

WHY THIS LOOK: this dashboard belongs to one developer whose personal brand
(portfolio, project branding) is a dark terminal aesthetic with amber/gold
accents. The dashboard should feel like it sits NEXT TO his other work — a
lived-in, slightly warm terminal — not a generic admin panel. Deliberately NOT:
pure-black hacker neon, cream-serif-terracotta, or corporate SaaS chrome.

COLOR — 6 base + 3 semantic, all in one warm tonal family:
  BG_VOID      #0a0d0a  near-black w/ green undertone (terminal void, not #000)
  BG_PANEL     #12160f  cards/panels, one step up from void
  BORDER_DIM   #262b22  hairlines — dim, never high-contrast
  TEXT_PRIMARY #d8dcd1  soft off-white (never pure white)
  TEXT_DIM     #6b7264  secondary text, timestamps, labels
  ACCENT_AMBER #e0a940  THE signature accent (owner's brand) — active states,
                        score-bar fill, current pipeline stage
  OK_OLIVE     #8fae5c  success / applied ("terminal green" without neon)
  WARN_ORANGE  #d98c3f  needs review / flagged
  FAIL_RUST    #a35c4a  failed / low fit (never bright alarm red)

TYPE — monospace identity is TOTAL, not partial:
  JetBrains Mono 600-700  → headers, buttons, numbers (tabular-nums for data)
  IBM Plex Mono 400       → body text (more readable at small sizes)

SIGNATURE ELEMENT — render_fit_score_bar(): a horizontal bar, amber fill
proportional to the score on a BORDER_DIM track, with the numeric score in
tabular-nums beside it. Length carries the meaning (works without color), the
number is always present (never bar-only). Identical on every page via this
one function — never reimplemented per page.

IMPLEMENTATION NOTE: CSS is injected via st.html() with all blank lines
stripped — markdown parsers terminate raw-HTML blocks at blank lines and spill
the rest as visible text (this repo hit that bug once; never again). A blanket
sidebar font override would break Streamlit's Material Symbols ligature icons,
so fonts are scoped and icons explicitly re-exempted.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import html
import re
from typing import List, Optional, Tuple

import streamlit as st

# --- Base tokens -------------------------------------------------------------- #
BG_VOID = "#0a0d0a"
BG_PANEL = "#12160f"
BORDER_DIM = "#262b22"
TEXT_PRIMARY = "#d8dcd1"
TEXT_DIM = "#6b7264"
ACCENT_AMBER = "#e0a940"

# --- Semantic tokens (same warm family) ---------------------------------------- #
OK_OLIVE = "#8fae5c"
WARN_ORANGE = "#d98c3f"
FAIL_RUST = "#a35c4a"

FONT_DISPLAY = "'JetBrains Mono', monospace"
FONT_BODY = "'IBM Plex Mono', monospace"

STATUS_COLORS = {
    "new": TEXT_DIM,
    "scored": TEXT_DIM,
    "queued": ACCENT_AMBER,
    "applied": OK_OLIVE,
    "submitted": OK_OLIVE,
    "skipped": TEXT_DIM,
    "needs_review": WARN_ORANGE,
    "needs_owner_input": WARN_ORANGE,
    "pending_review": WARN_ORANGE,
    "edited": ACCENT_AMBER,
    "sent": OK_OLIVE,
    "draft": TEXT_DIM,
    "failed": FAIL_RUST,
}
STATUS_LABELS = {
    "new": "discovered",
    "scored": "scored",
    "queued": "★ recommended",
    "applied": "applied",
    "skipped": "skipped",
    "needs_review": "needs review",
    "needs_owner_input": "needs your input",
    "pending_review": "pending review",
}


# ------------------------------------------------------------------------------ #
# CSS injection                                                                   #
# ------------------------------------------------------------------------------ #
def inject_theme() -> None:
    """Write fonts + the full stylesheet. Call once at the top of every page."""
    payload = f"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{ --bg-void:{BG_VOID}; --bg-panel:{BG_PANEL}; --border-dim:{BORDER_DIM};
  --text-primary:{TEXT_PRIMARY}; --text-dim:{TEXT_DIM}; --accent-amber:{ACCENT_AMBER}; }}
.stApp {{ background:{BG_VOID}; color:{TEXT_PRIMARY}; font-family:{FONT_BODY}; }}
[data-testid="stHeader"] {{ background:transparent; }}
[data-testid="stSidebar"] {{ background:{BG_PANEL}; border-right:1px solid {BORDER_DIM}; }}
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] span,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label {{ font-family:{FONT_BODY}; color:{TEXT_PRIMARY}; }}
[data-testid="stIconMaterial"], [class*="material-symbols"] {{ font-family:'Material Symbols Rounded' !important; }}
h1, h2, h3, h4 {{ font-family:{FONT_DISPLAY} !important; font-weight:700; color:{TEXT_PRIMARY}; letter-spacing:-0.01em; }}
h3, h4 {{ font-weight:600; }}
p, li, label, .stMarkdown {{ font-family:{FONT_BODY}; }}
a, a:visited {{ color:{ACCENT_AMBER}; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
code, kbd {{ font-family:{FONT_DISPLAY}; background:{BG_PANEL}; color:{TEXT_PRIMARY};
  border:1px solid {BORDER_DIM}; border-radius:3px; padding:1px 5px; }}
[data-testid="stCode"] pre, .stCode {{ background:{BG_PANEL} !important; border:1px solid {BORDER_DIM}; }}
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button, .stLinkButton>a {{
  font-family:{FONT_DISPLAY}; font-weight:600; font-size:.85rem; border-radius:4px;
  border:1px solid {BORDER_DIM}; background:{BG_PANEL}; color:{TEXT_PRIMARY};
  transition:border-color .12s ease, color .12s ease; }}
.stButton>button:hover, .stDownloadButton>button:hover, .stFormSubmitButton>button:hover, .stLinkButton>a:hover {{
  border-color:{ACCENT_AMBER}; color:{ACCENT_AMBER}; }}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"] {{
  background:{ACCENT_AMBER}; border-color:{ACCENT_AMBER}; color:{BG_VOID}; }}
.stButton>button[kind="primary"]:hover {{ background:#edbd5e; color:{BG_VOID}; }}
.stButton>button:disabled {{ color:{TEXT_DIM}; border-color:{BORDER_DIM}; }}
:focus-visible {{ outline:2px solid {ACCENT_AMBER} !important; outline-offset:2px; }}
.stButton>button:focus-visible {{ outline:2px solid {ACCENT_AMBER} !important; }}
[data-testid="stExpander"] {{ border:1px solid {BORDER_DIM}; border-radius:6px; background:{BG_PANEL}; }}
[data-testid="stExpander"] summary {{ font-family:{FONT_DISPLAY}; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:6px; }}
[data-baseweb="input"], [data-baseweb="select"], [data-baseweb="textarea"],
.stTextInput input, .stNumberInput input, .stTextArea textarea {{
  background:{BG_PANEL} !important; border-radius:4px !important;
  font-family:{FONT_BODY} !important; color:{TEXT_PRIMARY} !important; }}
[data-testid="stMetricValue"] {{ font-family:{FONT_DISPLAY}; font-variant-numeric:tabular-nums; color:{TEXT_PRIMARY}; }}
[data-testid="stMetricLabel"] {{ color:{TEXT_DIM}; font-family:{FONT_BODY}; }}
[data-testid="stDataFrame"] {{ font-family:{FONT_DISPLAY}; font-variant-numeric:tabular-nums; }}
/* --- signature: fit-score bar (length carries meaning; number always shown) --- */
.ja-fit {{ display:flex; align-items:center; gap:10px; }}
.ja-fit-bar {{ flex:0 0 150px; max-width:40vw; height:10px; background:{BORDER_DIM};
  border-radius:2px; overflow:hidden; }}
.ja-fit-bar>span {{ display:block; height:100%; background:{ACCENT_AMBER}; }}
.ja-fit-num {{ font-family:{FONT_DISPLAY}; font-weight:700; font-size:1.05rem;
  font-variant-numeric:tabular-nums; color:{ACCENT_AMBER}; min-width:2.4ch; text-align:right; }}
.ja-fit-num.dim {{ color:{TEXT_DIM}; }}
/* --- terminal chrome --- */
.ja-topbar {{ display:flex; justify-content:space-between; align-items:center;
  font-family:{FONT_DISPLAY}; font-size:.8rem; color:{TEXT_DIM};
  border-bottom:1px solid {BORDER_DIM}; padding-bottom:6px; margin-bottom:10px; }}
.ja-badge {{ font-family:{FONT_DISPLAY}; font-size:.8rem; }}
.ja-badge .on {{ color:{ACCENT_AMBER}; }}
.ja-badge .off {{ color:{FAIL_RUST}; }}
.ja-prompt {{ font-family:{FONT_DISPLAY}; font-size:.85rem; color:{TEXT_DIM}; margin:2px 0 14px 0; }}
.ja-prompt .p {{ color:{ACCENT_AMBER}; font-weight:600; }}
/* --- status pill / stage trail / rows --- */
.ja-pill {{ display:inline-block; padding:1px 9px; border-radius:3px; font-family:{FONT_DISPLAY};
  font-size:.72rem; font-weight:600; letter-spacing:.03em; border:1px solid; }}
.ja-trail {{ font-family:{FONT_DISPLAY}; font-size:.78rem; color:{TEXT_DIM}; letter-spacing:.02em; }}
.ja-trail .cur {{ color:{ACCENT_AMBER}; font-weight:600; }}
.ja-trail .sep {{ color:{BORDER_DIM}; padding:0 4px; }}
.ja-title {{ font-family:{FONT_DISPLAY}; font-weight:600; font-size:1.02rem; color:{TEXT_PRIMARY}; }}
.ja-meta {{ font-family:{FONT_DISPLAY}; font-size:.78rem; color:{TEXT_DIM}; font-variant-numeric:tabular-nums; }}
.ja-reason {{ color:{TEXT_DIM}; font-size:.86rem; }}
.ja-file {{ font-family:{FONT_DISPLAY}; font-size:.85rem; color:{TEXT_PRIMARY};
  font-variant-numeric:tabular-nums; }}
.ja-file .dim {{ color:{TEXT_DIM}; }}
.ja-comment {{ font-family:{FONT_DISPLAY}; font-size:.85rem; color:{TEXT_DIM}; margin:14px 0 2px 0; }}
.ja-comment .h {{ color:{ACCENT_AMBER}; }}
</style>"""
    payload = re.sub(r"\n\s*\n+", "\n", payload).strip()
    if hasattr(st, "html"):
        st.html(payload)
    else:  # very old Streamlit fallback
        st.markdown(payload, unsafe_allow_html=True)


# ------------------------------------------------------------------------------ #
# Signature component — THE fit-score bar (use everywhere, never reimplement)     #
# ------------------------------------------------------------------------------ #
def render_fit_score_bar(score) -> str:
    """HTML for the signature score bar: amber fill ∝ score + tabular number.

    Legible without color (length + number carry the meaning). Unscored jobs
    show an empty track and a dim em-dash — never a fabricated number.
    """
    if score is None:
        return ('<span class="ja-fit"><span class="ja-fit-bar"><span style="width:0%"></span></span>'
                '<span class="ja-fit-num dim">—</span></span>')
    pct = max(0.0, min(100.0, float(score)))
    return (f'<span class="ja-fit"><span class="ja-fit-bar"><span style="width:{pct:.0f}%"></span></span>'
            f'<span class="ja-fit-num">{pct:.0f}</span></span>')


# ------------------------------------------------------------------------------ #
# Terminal chrome helpers                                                         #
# ------------------------------------------------------------------------------ #
def provider_badge() -> str:
    """[●] ollama active — live LLM indicator, shown in the header of every page."""
    try:
        import api_client as api
        status = api.llm_status()
        name = status.get("active_provider", "?")
        return f'<span class="ja-badge"><span class="on">[●]</span> {html.escape(name)} active</span>'
    except Exception:
        return '<span class="ja-badge"><span class="off">[○]</span> backend offline</span>'


def page_header(title: str, cmd: str = "", subtitle: str = "") -> None:
    """Terminal-style header: app bar + $ command line + optional subtitle."""
    st.markdown(
        f'<div class="ja-topbar"><span>jobctl</span>{provider_badge()}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(f"# {title}")
    if cmd:
        st.markdown(f'<div class="ja-prompt"><span class="p">$</span> {html.escape(cmd)}</div>',
                    unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="ja-reason" style="margin:-6px 0 12px 0">{html.escape(subtitle)}</div>',
                    unsafe_allow_html=True)


def status_pill(status: str) -> str:
    color = STATUS_COLORS.get(status, TEXT_DIM)
    label = STATUS_LABELS.get(status, status.replace("_", " "))
    return (f'<span class="ja-pill" style="color:{color};border-color:{color}55;'
            f'background:{color}14">{html.escape(label)}</span>')


def stage_trail(stages: List[Tuple[str, bool]]) -> str:
    """Pipeline trail: discovered → scored (82) → tailored → applied.

    `stages` = [(label, is_current_or_reached_last)] — the LAST truthy stage is
    highlighted amber; connectors stay dim. Earned by real sequence data only.
    """
    parts = []
    last_idx = max((i for i, (_, on) in enumerate(stages) if on), default=-1)
    for i, (label, _) in enumerate(stages):
        cls = "cur" if i == last_idx else ""
        parts.append(f'<span class="{cls}">{html.escape(label)}</span>')
    sep = '<span class="sep">→</span>'
    return f'<span class="ja-trail">{sep.join(parts)}</span>'


def config_comment(text: str) -> None:
    """Settings section header styled like a YAML comment: # scoring"""
    st.markdown(f'<div class="ja-comment"><span class="h">#</span> {html.escape(text)}</div>',
                unsafe_allow_html=True)
