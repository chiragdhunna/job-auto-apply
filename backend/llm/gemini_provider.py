"""Gemini provider (primary).

Wraps google-generativeai behind the shared ``generate(prompt, expect_json)``
signature. The SDK import is deferred to first use so the whole system can run
on Ollama alone without google-generativeai installed.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend import config

logger = logging.getLogger("job_auto_apply.llm.gemini")


class GeminiError(RuntimeError):
    """Any failure from the Gemini provider (missing key, network, bad response)."""


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = (api_key if api_key is not None else config.GEMINI_API_KEY) or ""
        self.model_name = model or config.GEMINI_MODEL
        self._model = None  # lazily constructed

    def available(self) -> bool:
        """True if a non-empty API key is configured."""
        return bool(self.api_key)

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY is not set")
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - depends on env
            raise GeminiError(
                "google-generativeai is not installed. `pip install google-generativeai` "
                "or set LLM_PROVIDER=ollama."
            ) from exc
        genai.configure(api_key=self.api_key)
        self._model = genai.GenerativeModel(self.model_name)

    def generate(self, prompt: str, expect_json: bool = False) -> str:
        self._ensure_model()
        generation_config = {}
        if expect_json:
            # Constrain Gemini to emit valid JSON (no markdown fences).
            generation_config["response_mime_type"] = "application/json"
        try:
            response = self._model.generate_content(
                prompt,
                generation_config=generation_config or None,
            )
        except Exception as exc:  # network / rate-limit / invalid key / safety
            raise GeminiError(f"Gemini call failed: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            # Fall back to digging into candidates if .text is unavailable.
            try:
                text = response.candidates[0].content.parts[0].text
            except Exception:  # pragma: no cover
                text = None
        if not text:
            raise GeminiError("Gemini returned an empty response")
        return text.strip()
