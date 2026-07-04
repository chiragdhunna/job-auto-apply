"""Central configuration: loads environment (.env) and config/keywords.yaml.

Two layers of configuration:

1. **Environment** (secrets + provider selection) — read once at import.
2. **keywords.yaml** — the job-search defaults (roles, locations, threshold,
   platform toggles, run interval). These are the *defaults*; the ``settings``
   DB table stores runtime overrides edited from the dashboard/API.

``base_resume_data.json`` (the owner's structured resume) is also loaded here so
the scorer / resume tailor / answer generator share one accessor.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------- #
# Paths                                                                        #
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
CONFIG_DIR = BASE_DIR / "config"
KEYWORDS_PATH = CONFIG_DIR / "keywords.yaml"
BASE_RESUME_PATH = CONFIG_DIR / "base_resume_data.json"

# --------------------------------------------------------------------------- #
# Environment-backed settings                                                  #
# --------------------------------------------------------------------------- #
GEMINI_API_KEY: str = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL: str = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()

LLM_PROVIDER: str = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
OLLAMA_HOST: str = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").strip().rstrip("/")
OLLAMA_MODEL: str = (os.getenv("OLLAMA_MODEL") or "llama3.1:8b").strip()

LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")
INDEED_EMAIL: str = os.getenv("INDEED_EMAIL", "")
INDEED_PASSWORD: str = os.getenv("INDEED_PASSWORD", "")

DB_PATH: str = os.getenv("DB_PATH", "./data/jobs.db")
BROWSER_PROFILE_DIR: str = os.getenv("BROWSER_PROFILE_DIR", "./browser_profiles/default")

try:
    MAX_APPLICATIONS_PER_RUN: int = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "10") or 10)
except ValueError:
    MAX_APPLICATIONS_PER_RUN = 10

# --------------------------------------------------------------------------- #
# Defaults                                                                     #
# --------------------------------------------------------------------------- #
DEFAULT_PLATFORM_TOGGLES: Dict[str, bool] = {
    "linkedin": True,
    "indeed": True,
    "greenhouse": True,
    "lever": True,
    "workday": True,
}

# Keys that are runtime-tunable and therefore stored in the settings table
# (overriding the keywords.yaml defaults when set).
RUNTIME_SETTING_KEYS = ("score_threshold", "platform_toggles", "run_interval_minutes")

_VALID_PROVIDERS = ("auto", "gemini", "ollama")


# --------------------------------------------------------------------------- #
# Loaders                                                                      #
# --------------------------------------------------------------------------- #
def load_keywords() -> Dict[str, Any]:
    """Parse config/keywords.yaml (returns {} if missing)."""
    if KEYWORDS_PATH.exists():
        with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_base_resume_data() -> Dict[str, Any]:
    """Parse config/base_resume_data.json (returns {} if missing)."""
    if BASE_RESUME_PATH.exists():
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def target_roles() -> List[str]:
    return list(load_keywords().get("target_roles", []) or [])


def target_locations() -> List[str]:
    return list(load_keywords().get("locations", []) or [])


def exclude_companies() -> List[str]:
    return [c.lower() for c in (load_keywords().get("exclude_companies", []) or [])]


def keywords_defaults() -> Dict[str, Any]:
    """Effective defaults for the runtime-tunable settings, sourced from YAML."""
    kw = load_keywords()
    platforms = kw.get("platforms") or {}
    toggles = {**DEFAULT_PLATFORM_TOGGLES, **platforms}
    return {
        "score_threshold": kw.get("score_threshold", 70),
        "platform_toggles": toggles,
        "run_interval_minutes": kw.get("run_interval_minutes", 60),
    }


def active_provider_name() -> str:
    """Which provider will be used *by configuration* (static, not a live check).

    For ``auto``: Gemini if a key is present, else Ollama.
    """
    if LLM_PROVIDER == "gemini":
        return "gemini"
    if LLM_PROVIDER == "ollama":
        return "ollama"
    return "gemini" if GEMINI_API_KEY else "ollama"


def provider_setting_is_valid() -> bool:
    return LLM_PROVIDER in _VALID_PROVIDERS
