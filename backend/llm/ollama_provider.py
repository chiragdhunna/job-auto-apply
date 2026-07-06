"""Ollama provider (local fallback).

Talks to a locally-running Ollama server via its HTTP ``/api/generate`` endpoint.
For ``expect_json=True`` we pass ``format: "json"`` because local models are less
reliable than Gemini at strict JSON without it.

If Ollama isn't reachable we raise :class:`OllamaUnavailableError` with an
actionable message rather than failing silently.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from backend import config

logger = logging.getLogger("job_auto_apply.llm.ollama")


class OllamaError(RuntimeError):
    """Generic Ollama failure (bad model, HTTP error, empty response)."""


class OllamaUnavailableError(OllamaError):
    """Ollama server could not be reached at the configured host."""


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.host = (host or config.OLLAMA_HOST).rstrip("/")
        self.model = model or config.OLLAMA_MODEL
        # Default comes from OLLAMA_TIMEOUT in .env (600s). Long generations
        # (tailored resume LaTeX) routinely exceed a couple of minutes on CPU.
        self.timeout = timeout if timeout is not None else config.OLLAMA_TIMEOUT

    def is_reachable(self) -> bool:
        """Quick liveness check used by the dashboard/settings status view."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def available(self) -> bool:
        return self.is_reachable()

    def generate(self, prompt: str, expect_json: bool = False) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if expect_json:
            payload["format"] = "json"
        try:
            resp = requests.post(
                f"{self.host}/api/generate", json=payload, timeout=self.timeout
            )
        except requests.ConnectionError as exc:
            raise OllamaUnavailableError(
                f"Ollama not reachable at {self.host}. Is it running? Start it with "
                f"`ollama serve` and pull a model with `ollama pull {self.model}`."
            ) from exc
        except requests.Timeout as exc:
            raise OllamaError(
                f"Ollama timed out after {self.timeout}s while generating with "
                f"'{self.model}'. Long outputs (e.g. a tailored resume in LaTeX) can "
                f"exceed this on CPU-only machines. Fix: increase OLLAMA_TIMEOUT in "
                f".env, use a faster model, or set GEMINI_API_KEY to use Gemini."
            ) from exc
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        if resp.status_code == 404:
            raise OllamaError(
                f"Ollama model '{self.model}' not found. Pull it with "
                f"`ollama pull {self.model}`."
            )
        if resp.status_code != 200:
            raise OllamaError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a non-JSON envelope") from exc

        text = (data or {}).get("response", "")
        if not text:
            raise OllamaError("Ollama returned an empty response")
        return text.strip()
