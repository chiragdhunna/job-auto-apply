"""LLMClient: provider selection + automatic fallback.

Resolution rules (driven by LLM_PROVIDER in .env, default "auto"):

  gemini  -> Gemini only (raises if a call fails; explicit choice, no fallback)
  ollama  -> Ollama only
  auto    -> Gemini as primary if GEMINI_API_KEY is set, otherwise Ollama;
             if a Gemini call fails (rate limit / network / invalid key),
             automatically fall back to Ollama and log the fallback.

Public surface:
  generate(prompt, expect_json=False) -> str   (module-level convenience)
  get_client() -> LLMClient                     (process-wide singleton)
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from backend import config
from backend.llm.gemini_provider import GeminiError, GeminiProvider
from backend.llm.ollama_provider import OllamaError, OllamaProvider

logger = logging.getLogger("job_auto_apply.llm")

_PROVIDER_ERRORS = (GeminiError, OllamaError)


class LLMError(RuntimeError):
    """Raised when generation fails on the active provider (and any fallback)."""


class LLMClient:
    def __init__(self, provider_setting: Optional[str] = None) -> None:
        self.provider_setting = (provider_setting or config.LLM_PROVIDER or "auto").lower()
        self.gemini = GeminiProvider()
        self.ollama = OllamaProvider()

    # -- resolution --------------------------------------------------------- #
    def _primary_and_fallback(self):
        """Return (primary_provider, fallback_provider_or_None)."""
        setting = self.provider_setting
        if setting == "gemini":
            return self.gemini, None
        if setting == "ollama":
            return self.ollama, None
        # auto
        if self.gemini.available():
            return self.gemini, self.ollama
        return self.ollama, None

    def active_provider_name(self) -> str:
        primary, _ = self._primary_and_fallback()
        return primary.name

    # -- generation --------------------------------------------------------- #
    def generate(self, prompt: str, expect_json: bool = False) -> str:
        primary, fallback = self._primary_and_fallback()
        try:
            return primary.generate(prompt, expect_json=expect_json)
        except _PROVIDER_ERRORS as exc:
            if fallback is None:
                raise LLMError(
                    f"LLM provider '{primary.name}' failed and no fallback is configured: {exc}"
                ) from exc
            logger.warning(
                "Primary LLM provider '%s' failed (%s). Falling back to '%s'.",
                primary.name,
                exc,
                fallback.name,
            )
            try:
                return fallback.generate(prompt, expect_json=expect_json)
            except _PROVIDER_ERRORS as exc2:
                raise LLMError(
                    f"Both LLM providers failed. {primary.name}: {exc} | "
                    f"{fallback.name}: {exc2}"
                ) from exc2

    # -- introspection (for the dashboard/settings status view) ------------- #
    def status(self) -> dict:
        primary, fallback = self._primary_and_fallback()
        return {
            "provider_setting": self.provider_setting,
            "active_provider": primary.name,
            "fallback_provider": fallback.name if fallback else None,
            "gemini": {
                "available": self.gemini.available(),
                "model": self.gemini.model_name,
            },
            "ollama": {
                "host": self.ollama.host,
                "model": self.ollama.model,
                "reachable": self.ollama.is_reachable(),
            },
        }


# --------------------------------------------------------------------------- #
# Process-wide singleton + convenience function                               #
# --------------------------------------------------------------------------- #
_client: Optional[LLMClient] = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
        logger.info(
            "LLM client initialized (setting=%s, active=%s).",
            _client.provider_setting,
            _client.active_provider_name(),
        )
    return _client


def generate(prompt: str, expect_json: bool = False) -> str:
    """Route a single prompt through the active provider (with fallback)."""
    return get_client().generate(prompt, expect_json=expect_json)
