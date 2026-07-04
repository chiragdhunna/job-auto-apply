"""LLM abstraction layer.

Every LLM-dependent module (scoring, resume tailoring, answer generation) routes
through :func:`backend.llm.client.generate` rather than calling a provider SDK
directly. This keeps provider selection + fallback logic in one place.

    from backend.llm.client import generate
    text = generate("prompt", expect_json=True)
"""

from backend.llm.client import LLMClient, LLMError, generate, get_client

__all__ = ["LLMClient", "LLMError", "generate", "get_client"]
