"""Provider selection driven by configuration."""

from __future__ import annotations

from trussflow.config import Settings, get_logger, get_settings
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import StubProvider

logger = get_logger("llm.factory")


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the configured provider, defaulting to the offline stub."""
    settings = settings or get_settings()
    choice = settings.llm_provider
    if choice in ("stub", "offline", "mock"):
        logger.info("Using offline stub LLM provider")
        return StubProvider()
    if choice == "gemini":
        from trussflow.llm.gemini import GeminiProvider

        logger.info("Using Gemini LLM provider (%s)", settings.gemini_model)
        return GeminiProvider(settings)
    raise ValueError(f"Unknown TRUSSFLOW_LLM_PROVIDER: {choice!r}")
