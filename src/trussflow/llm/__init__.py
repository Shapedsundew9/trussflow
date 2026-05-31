"""Pluggable LLM provider layer.

The pipeline depends only on the :class:`LLMProvider` protocol. A deterministic
offline :class:`StubProvider` lets the whole flow run without an API key, while
:class:`GeminiProvider` wires in Google Gemini when configured.
"""

from trussflow.llm.base import LLMProvider, LLMResponse
from trussflow.llm.factory import get_provider

__all__ = ["LLMProvider", "LLMResponse", "get_provider"]
