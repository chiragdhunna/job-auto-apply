"""Design system for the job-auto-apply dashboard.

═══════════════════════════════════════════════════════════════════════════════
DESIGN TOKENS  (edit here; every page imports from this module for consistency)
═══════════════════════════════════════════════════════════════════════════════

WHY THIS LOOK (not a generic dashboard template):
  This is a daily triage tool for ONE developer deciding which jobs are worth
  applying to. Its single job: let the fit score be trusted at a glance. So the
  score — not chrome — is the hero, and colour is spent on *meaning*.

  · Canvas — a deep "control-room" navy (#0E1621), chosen deliberately (not the
    reflexive black+neon): the darkness exists so the semantic SCORE GRADIENT
    reads with maximum contrast. It is a focus surface, checked daily.
  · Score gradient — green → lime → amber → clay encodes fit strength as a real
    progression (95 ≠ 70). This is the palette's heart and the app's signature.
  · Action blue (#4C9DF7) is reserved for interactive things (buttons, links,
    focus). "Fit" (green/amber) and "do" (blue) never share a colour, so a high
    score never looks like a button and vice-versa.

TYPE (a considered trio, not Inter-everywhere):
  · Space Grotesk — display / headings (geometric, a little character)
  · IBM Plex Sans — body copy (humanist, highly readable, distinct from Inter)
  · IBM Plex Mono — scores, dates, counts, tabular data (data deserves a mono)

SIGNATURE ELEMENT — the score chip: a colour-banded block showing the number
(mono), a fit-band LABEL, and a fill bar. Never colour-alone (accessibility):
the band label + number carry the meaning for anyone who can't distinguish hue.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import html
from typing import Tuple

import streamlit as st

# --- Colour tokens ---------------------------------------------------------- #
BG = "#0E1621"          # app canvas — deep control-room navy
SURFACE = "#18222E"     # cards / containers
ELEVATED = "#212E3C"    # inputs, raised chrome
BORDER = "#30404F"      # hairlines
TEXT = "#E7EDF3"        # primary text
MUTED = "#93A4B7"       # secondary text
ACCENT = "#4C9DF7"      # interactive: buttons, links, focus (NEVER used for score)
ACCENT_HOVER = "#6FB2FF"

# Semantic score gradient (fit strength). Paired ALWAYS with a text label.
SCORE_STRONG = "#20B26C"    # >= 85  strong
SCORE_GOOD = "#7FB83F"      # 70-84  good
SCORE_MODERATE = "#E0A83D"  # 55-69  moderate
SCORE_WEAK = "#C4634E"      # < 55   weak

# Pipeline status colours (progression: discovered → recommended → applied)
STATUS_COLORS = {
    "new": "#6C7A8A",
    "scored": "#5E8CC4",
    "queued": "#4C9DF7",        # recommended
    "applied": "#20B26C",
    "skipped": "#6C7A8A",
    "needs_review": "#E0A83D",
    "failed": "#C4634E",
}
STATUS_LABELS = {
    "new": "Discovered",
    "scored": "Scored",
    "queued": "★ Recommended",
    "applied": "Applied",
    "skipped": "Skipped",
    "needs_review": "Needs review",
    "failed": "Failed",
}

FONT_DISPLAY = "'Space Grotesk', sans-serif"
FONT_BODY = "'IBM Plex Sans', sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"


def fit_band(score) -> Tuple[str, str]:
    """Return (label, hex colour) for a fit score. Label carries meaning w/o hue."""
    if score is None:
        return "Unscored", MUTED
    s = float(score)
    if s >= 85:
        return "Strong fit", SCORE_STRONG
    if s >= 70:
        return "Good fit", SCORE_GOOD
    if s >= 55:
        return "Moderate", SCORE_MODERATE
    return "Weak fit", SCORE_WEAK


# --------------------------------------------------------------------------- #
# CSS injection                                                                #
# --------------------------------------------------------------------------- #
def inject_theme() -> None:
    """Inject fonts + the global stylesheet. Call once at the top of each page."""
    st.markdown(
        f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --ja-bg:{BG}; --ja-surface:{SURFACE}; --ja-elevated:{ELEVATED};
  --ja-border:{BORDER}; --ja-text:{TEXT}; --ja-muted:{MUTED};
  --ja-accent:{ACCENT}; --ja-accent-hover:{ACCENT_HOVER};
}}
.stApp {{ background:{BG}; color:{TEXT}; font-family:{FONT_BODY}; }}
[data-testid="stHeader"] {{ background:transparent; }}
[data-testid="stSidebar"] {{ background:{SURFACE}; border-right:1px solid {BORDER}; }}
[data-testid="stSidebar"] * {{ font-family:{FONT_BODY}; }}

h1,h2,h3,h4 {{ font-family:{FONT_DISPLAY} !important; color:{TEXT}; letter-spacing:-0.01em; }}
h1 {{ font-weight:700; }}
a, a:visited {{ color:{ACCENT}; text-decoration:none; }}
a:hover {{ color:{ACCENT_HOVER}; text-decoration:underline; }}
code, kbd {{ font-family:{FONT_MONO}; background:{ELEVATED}; color:{TEXT}; }}

/* Buttons — the one interactive accent */
.stButton>button, .stDownloadButton>button, .stLinkButton>a {{
  font-family:{FONT_BODY}; font-weight:600; border-radius:8px;
  border:1px solid {BORDER}; background:{ELEVATED}; color:{TEXT};
  transition:border-color .15s ease, background .15s ease;
}}
.stButton>button:hover, .stDownloadButton>button:hover, .stLinkButton>a:hover {{
  border-color:{ACCENT}; color:{ACCENT_HOVER};
}}
.stButton>button[kind="primary"] {{ background:{ACCENT}; border-color:{ACCENT}; color:#08131f; }}
.stButton>button[kind="primary"]:hover {{ background:{ACCENT_HOVER}; color:#08131f; }}
:focus-visible {{ outline:2px solid {ACCENT} !important; outline-offset:2px; }}

/* Cards (bordered containers) + expanders */
[data-testid="stExpander"] {{ border:1px solid {BORDER}; border-radius:10px; background:{SURFACE}; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:12px; }}

/* Inputs */
[data-baseweb="input"], [data-baseweb="select"], .stTextInput input, .stNumberInput input {{
  background:{ELEVATED} !important; border-radius:8px !important;
}}
[data-testid="stMetricValue"] {{ font-family:{FONT_MONO}; color:{TEXT}; }}
[data-testid="stMetricLabel"] {{ color:{MUTED}; }}

/* --- signature: score chip --- */
.ja-score {{
  display:flex; flex-direction:column; gap:4px; align-items:center;
  padding:10px 8px; border-radius:10px; background:{ELEVATED};
  border:1px solid {BORDER}; border-left:4px solid var(--band,{MUTED}); min-width:92px;
}}
.ja-score-num {{ font-family:{FONT_MONO}; font-weight:600; font-size:1.7rem; line-height:1; color:var(--band,{TEXT}); }}
.ja-score-band {{ font-family:{FONT_BODY}; font-size:.68rem; font-weight:600; text-transform:uppercase;
  letter-spacing:.04em; color:{MUTED}; text-align:center; }}
.ja-score-bar {{ width:100%; height:4px; border-radius:2px; background:{BORDER}; overflow:hidden; }}
.ja-score-bar>span {{ display:block; height:100%; background:var(--band,{MUTED}); }}

/* --- status pill --- */
.ja-pill {{ display:inline-block; padding:2px 10px; border-radius:999px; font-family:{FONT_BODY};
  font-size:.72rem; font-weight:600; border:1px solid; }}

/* --- job card meta --- */
.ja-title {{ font-family:{FONT_DISPLAY}; font-weight:600; font-size:1.06rem; color:{TEXT}; }}
.ja-company {{ color:{TEXT}; font-weight:500; }}
.ja-meta {{ font-family:{FONT_MONO}; font-size:.78rem; color:{MUTED}; }}
.ja-reason {{ color:{MUTED}; font-size:.9rem; }}
.ja-eyebrow {{ font-family:{FONT_MONO}; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:{ACCENT}; }}
</style>
""",
        unsafe_allow_html=True,
    )


def score_chip(score) -> str:
    """HTML for the signature score chip. Render with unsafe_allow_html=True."""
    label, color = fit_band(score)
    num = "—" if score is None else f"{float(score):.0f}"
    pct = 0 if score is None else max(0, min(100, float(score)))
    return (
        f'<div class="ja-score" style="--band:{color}">'
        f'<span class="ja-score-num">{num}</span>'
        f'<span class="ja-score-band">{html.escape(label)}</span>'
        f'<span class="ja-score-bar"><span style="width:{pct}%"></span></span>'
        f"</div>"
    )


def status_pill(status: str) -> str:
    color = STATUS_COLORS.get(status, MUTED)
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    return (
        f'<span class="ja-pill" style="color:{color};border-color:{color}33;'
        f'background:{color}1a">{html.escape(label)}</span>'
    )


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    eb = f'<div class="ja-eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""
    sub = f'<div class="ja-reason" style="margin-top:2px">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'{eb}<h1 style="margin:0 0 2px 0">{html.escape(title)}</h1>{sub}',
        unsafe_allow_html=True,
    )
