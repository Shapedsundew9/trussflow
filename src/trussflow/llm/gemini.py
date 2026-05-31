"""Google Gemini LLM provider.

Only imported lazily when selected, so the prototype runs without the
``google-genai`` package installed unless the live provider is requested.
"""

from __future__ import annotations

from trussflow.config import Settings, get_settings
from trussflow.llm.base import LLMResponse


class GeminiProvider:
    """Provider backed by Google Gemini via the ``google-genai`` SDK."""

    name = "gemini"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set; cannot use the Gemini provider."
            )
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency.
            raise RuntimeError(
                "google-genai is not installed. Install with "
                "'pip install trussflow[gemini]'."
            ) from exc
        self._client = genai.Client(api_key=self._settings.gemini_api_key)

    def complete(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        config = {"response_mime_type": "application/json"} if json_mode else None
        response = self._client.models.generate_content(
            model=self._settings.gemini_model,
            contents=prompt,
            config=config,
        )
        return LLMResponse(text=response.text or "", provider=self.name, raw=response)
