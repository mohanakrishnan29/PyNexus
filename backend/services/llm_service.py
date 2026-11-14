"""Provider-neutral interface for response-generation services."""
from __future__ import annotations

from typing import Dict, Optional, Protocol

from backend.utils.config import settings


class LLMService(Protocol):
    """The boundary between the RAG pipeline and an LLM provider."""

    provider_name: str

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        history: Optional[list[Dict[str, str]]] = None,
    ) -> str:
        """Return a Markdown response for the supplied system and user prompts."""


def get_llm_service() -> LLMService:
    """Create the configured provider without leaking provider details to RAG code."""
    settings.validate_llm()
    if settings.llm_provider == "gemini":
        from backend.services.gemini_service import GeminiService

        return GeminiService(api_key=settings.gemini_api_key, model_name=settings.gemini_model)
    raise RuntimeError(f"Unsupported LLM_PROVIDER '{settings.llm_provider}'.")