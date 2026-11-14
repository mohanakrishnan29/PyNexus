"""Google Gemini implementation of the application's LLM service."""
from __future__ import annotations

from typing import Dict, Optional


class GeminiService:
    """Encapsulates all Google Gemini SDK and message-format details."""

    provider_name = "gemini"

    def __init__(self, *, api_key: str, model_name: str) -> None:
        if not api_key.strip():
            raise RuntimeError("GEMINI_API_KEY must be configured when LLM_PROVIDER=gemini.")
        if not model_name.strip():
            raise RuntimeError("GEMINI_MODEL must name a Gemini model.")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on installation
            raise RuntimeError(
                "The Google Gemini SDK is missing. Install dependencies with 'pip install -r requirements.txt'."
            ) from exc

        self._client = genai.Client(api_key=api_key)
        self._model_name = model_name

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        history: Optional[list[Dict[str, str]]] = None,
    ) -> str:
        history_lines = []
        for turn in (history or [])[-6:]:
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                continue
            history_lines.append(f"{'Assistant' if role == 'assistant' else 'User'}: {content.strip()}")
        history_lines.append(f"User: {user_prompt}")

        try:
            interaction = self._client.interactions.create(
                model=self._model_name,
                system_instruction=system_prompt,
                input="\n\n".join(history_lines),
                generation_config={"temperature": 0.1},
                # RAG history is managed by the application; do not persist it remotely.
                store=False,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Gemini generation failed for model '{self._model_name}'. Verify GEMINI_API_KEY and GEMINI_MODEL."
            ) from exc

        answer = (getattr(interaction, "output_text", None) or "").strip()
        if not answer:
            raise RuntimeError(f"Gemini returned an empty response for model '{self._model_name}'.")
        return answer