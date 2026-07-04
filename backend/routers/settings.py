"""Settings API.

GET  /settings         -> effective runtime settings + configured LLM provider
PUT  /settings         -> update any of score_threshold / platform_toggles /
                          run_interval_minutes (persisted to the settings table)

Effective value = DB override if present, else the keywords.yaml default.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import config
from backend.db import crud
from backend.db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    score_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    platform_toggles: Optional[Dict[str, bool]] = None
    run_interval_minutes: Optional[int] = Field(default=None, ge=1)


def effective_settings(db: Session) -> Dict[str, Any]:
    defaults = config.keywords_defaults()
    toggles = crud.get_setting(db, "platform_toggles", defaults["platform_toggles"])
    # Merge so newly-added platforms always appear even if the stored value is old.
    merged_toggles = {**config.DEFAULT_PLATFORM_TOGGLES, **(toggles or {})}
    return {
        "score_threshold": crud.get_setting(db, "score_threshold", defaults["score_threshold"]),
        "platform_toggles": merged_toggles,
        "run_interval_minutes": crud.get_setting(
            db, "run_interval_minutes", defaults["run_interval_minutes"]
        ),
    }


def _with_provider(db: Session) -> Dict[str, Any]:
    data = effective_settings(db)
    data["llm_provider_configured"] = config.active_provider_name()
    data["llm_provider_setting"] = config.LLM_PROVIDER
    return data


@router.get("")
def get_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _with_provider(db)


@router.get("/llm-status")
def llm_status() -> Dict[str, Any]:
    """Live LLM status: active provider + whether Ollama is currently reachable.

    Surfaced on the dashboard Settings page so the owner can see at a glance
    which provider is actually being used.
    """
    from backend.llm.client import get_client

    return get_client().status()


@router.put("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if payload.score_threshold is not None:
        crud.set_setting(db, "score_threshold", payload.score_threshold)
    if payload.platform_toggles is not None:
        # Merge with existing so a partial update doesn't drop other platforms.
        current = effective_settings(db)["platform_toggles"]
        current.update(payload.platform_toggles)
        crud.set_setting(db, "platform_toggles", current)
    if payload.run_interval_minutes is not None:
        crud.set_setting(db, "run_interval_minutes", payload.run_interval_minutes)
    db.commit()
    return _with_provider(db)
