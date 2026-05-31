"""Pluggable LLM provider layer.

The pipeline depends only on the :class:`LLMProvider` protocol. A deterministic
offline :class:`StubProvider` lets the whole flow run without network access,
while :class:`CopilotProvider` drives the GitHub Copilot CLI when configured.
"""

from trussflow.llm.base import LLMProvider, LLMResponse
from trussflow.llm.copilot import CopilotProvider, CopilotSession
from trussflow.llm.factory import get_provider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "CopilotProvider",
    "CopilotSession",
    "get_provider",
]
