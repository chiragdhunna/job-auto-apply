"""Settings API.

GET  /settings         -> effective runtime settings + configured LLM provider
PUT  /settings         -> update any of score_threshold / platform_toggles /
                          run_interval_minutes (persisted to the settings table)

Effective value = DB override if present, else the keywords.yaml default.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend import config
from backend.db import crud
from backend.db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    score_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    platform_toggles: Optional[Dict[str, bool]] = None
    source_toggles: Optional[Dict[str, bool]] = None
    run_interval_minutes: Optional[int] = Field(default=None, ge=1)


def effective_settings(db: Session) -> Dict[str, Any]:
    defaults = config.keywords_defaults()
    toggles = crud.get_setting(db, "platform_toggles", defaults["platform_toggles"])
    # Merge so newly-added platforms always appear even if the stored value is old.
    merged_toggles = {**config.DEFAULT_PLATFORM_TOGGLES, **(toggles or {})}
    src_defaults = config.source_defaults()
    src_toggles = crud.get_setting(db, "source_toggles", src_defaults)
    merged_sources = {**config.DEFAULT_SOURCE_TOGGLES, **src_defaults, **(src_toggles or {})}
    return {
        "score_threshold": crud.get_setting(db, "score_threshold", defaults["score_threshold"]),
        "platform_toggles": merged_toggles,
        "source_toggles": merged_sources,
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


class ClearDataRequest(BaseModel):
    delete_resume_files: bool = True
    include_settings: bool = False
    confirm: str = ""


@router.post("/clear-data")
def clear_data(payload: ClearDataRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """DANGER: wipe all jobs, applications, and resume versions.

    Requires confirm == "DELETE". Settings survive unless include_settings.
    Optionally removes the generated PDF files in data/resumes/.
    """
    if payload.confirm != "DELETE":
        raise HTTPException(
            status_code=400, detail='Confirmation required: pass {"confirm": "DELETE"}.'
        )
    counts = crud.clear_all_data(db, include_settings=payload.include_settings)

    files_deleted = 0
    if payload.delete_resume_files:
        from backend.resume_tailor.latex_engine import RESUME_DIR

        if RESUME_DIR.exists():
            for f in RESUME_DIR.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        files_deleted += 1
                    except OSError:
                        pass
    counts["resume_files"] = files_deleted
    return {"cleared": True, **counts}


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
    if payload.source_toggles is not None:
        current = effective_settings(db)["source_toggles"]
        current.update(payload.source_toggles)
        crud.set_setting(db, "source_toggles", current)
    if payload.run_interval_minutes is not None:
        crud.set_setting(db, "run_interval_minutes", payload.run_interval_minutes)
    db.commit()
    return _with_provider(db)
