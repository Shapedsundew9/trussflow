"""LLM provider protocol and shared response type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """A normalized LLM response.

    ``text`` is the raw model output. ``raw`` retains the provider-native
    payload for transparency and debugging.
    """

    text: str
    provider: str
    raw: object | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal contract every provider must satisfy."""

    name: str

    def complete(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        """Return a completion for ``prompt``.

        When ``json_mode`` is True the provider should bias toward returning a
        single valid JSON document.
        """
        ...
