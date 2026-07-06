"""Shared Playwright launch configuration + human-like interaction helpers.

Anti-detection measures (see README):
  * NON-headless, persistent browser context (real Chrome profile dir) so cookies
    / sessions persist across runs and there is no fresh-automation fingerprint.
  * Randomised delays between every action — never fixed sleeps.
  * Character-by-character typing with per-key jitter.
  * Mouse movement toward an element before clicking it.
  * `navigator.webdriver` masked; automation blink feature disabled.
  * Per-run application caps enforced by the callers.

All timing helpers derive from ``random`` so no two runs look identical.
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend import config

logger = logging.getLogger("job_auto_apply.automation")

DEFAULT_VIEWPORT = {"width": 1366, "height": 850}

# A recent, common desktop Chrome UA. Keep in sync with the bundled Chromium.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--start-maximized",
]

_INIT_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def setup_automation_logging() -> None:
    """Attach a file handler so every automated action is logged for debugging."""
    log_dir = Path(config.BASE_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "automation.log"
    root = logging.getLogger("job_auto_apply")
    if not any(getattr(h, "_ja_file", None) == str(log_path) for h in root.handlers):
        handler = logging.FileHandler(log_path)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._ja_file = str(log_path)  # type: ignore[attr-defined]
        root.addHandler(handler)
        root.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Timing                                                                       #
# --------------------------------------------------------------------------- #
def human_delay(min_s: float = 1.0, max_s: float = 4.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def short_delay() -> None:
    time.sleep(random.uniform(0.25, 1.1))


def long_delay() -> None:
    time.sleep(random.uniform(3.0, 8.0))


# --------------------------------------------------------------------------- #
# Context / interaction                                                        #
# --------------------------------------------------------------------------- #
def launch_persistent_context(playwright, *, headless: bool = False, profile_dir: Optional[str] = None):
    """Launch a persistent Chromium context using the owner's profile directory.

    NEVER default to headless for LinkedIn/Indeed — it raises detection risk.
    """
    profile = profile_dir or config.BROWSER_PROFILE_DIR
    Path(profile).mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=profile,
        headless=headless,
        args=LAUNCH_ARGS,
        viewport=DEFAULT_VIEWPORT,
        user_agent=USER_AGENT,
        locale="en-GB",
    )
    try:
        context.add_init_script(_INIT_STEALTH_JS)
    except Exception:  # pragma: no cover - best effort
        logger.debug("Could not add stealth init script", exc_info=True)
    return context


def wait_for_manual_login(context, service_name: str) -> None:
    """Block until the owner finishes logging in manually.

    Preferred: press Enter in the terminal. On consoles where stdin is not a
    TTY (e.g. Git Bash / mintty on Windows without winpty), ``input()`` raises
    EOFError immediately — in that case fall back to waiting until the owner
    CLOSES the browser window, so the login session is still saved.
    """
    import sys
    import time as _time

    if sys.stdin is not None and sys.stdin.isatty():
        print(
            f"Log in to {service_name} in the opened window, then press Enter "
            f"here to save the session…"
        )
        try:
            input()
            return
        except EOFError:
            pass  # fall through to window-close detection
    print(
        f"(No interactive terminal detected — log in to {service_name} in the "
        f"opened window, then simply CLOSE the browser window to save the session. "
        f"Tip for Git Bash: `winpty python -m ...` makes Enter work here.)"
    )
    try:
        while context.pages:
            _time.sleep(2)
    except Exception:
        # Context/browser already gone — that's exactly our exit condition.
        pass


def human_type(locator, text: str, *, clear: bool = True) -> None:
    """Type into a locator character-by-character with jitter."""
    if text is None:
        return
    locator.scroll_into_view_if_needed()
    locator.click()
    short_delay()
    if clear:
        try:
            locator.fill("")
        except Exception:
            pass
    page = locator.page
    for ch in str(text):
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.03, 0.16))
    short_delay()


def human_click(locator) -> None:
    """Move the mouse toward an element, then click it."""
    locator.scroll_into_view_if_needed()
    short_delay()
    try:
        box = locator.bounding_box()
        if box:
            page = locator.page
            tx = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
            ty = box["y"] + box["height"] / 2 + random.uniform(-4, 4)
            page.mouse.move(tx, ty, steps=random.randint(6, 18))
            human_delay(0.2, 0.7)
    except Exception:  # pragma: no cover
        logger.debug("mouse move before click failed", exc_info=True)
    locator.click()


# --------------------------------------------------------------------------- #
# Applicant details                                                            #
# --------------------------------------------------------------------------- #
def applicant_from_resume(base_resume_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the common application fields from base_resume_data.json."""
    name = (base_resume_data.get("name") or "").strip()
    parts = name.split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    links = base_resume_data.get("links") or {}
    return {
        "full_name": name,
        "first_name": first,
        "last_name": last,
        "email": base_resume_data.get("email", ""),
        "phone": base_resume_data.get("phone", ""),
        "location": base_resume_data.get("location", ""),
        "linkedin": links.get("linkedin", ""),
        "github": links.get("github", ""),
        "portfolio": links.get("portfolio", ""),
    }


def first_locator(page, selectors: List[str]):
    """Return the first selector (from a fallback list) that resolves to a
    visible element, or None. ATS DOMs change often, so we try several."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None
