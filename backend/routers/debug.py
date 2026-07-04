"""Debug endpoints used to verify the system before higher layers rely on it.

GET /debug/llm-check   -> sends a trivial prompt through the active provider and
                          returns the response. Verifies the LLM layer works
                          before scoring / tailoring / answers build on it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.llm.client import LLMError, get_client

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/llm-check")
def llm_check() -> dict:
    client = get_client()
    prompt = "Reply with one short sentence confirming the connection works."
    try:
        response = client.generate(prompt)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "active_provider": client.active_provider_name(),
        "prompt": prompt,
        "response": response,
    }
