"""Prompt loading with mechanical placeholder substitution.

Per ``docs/design/agent-flow.md``, prompt templates live as files and have
``{{PLACEHOLDER}}`` tokens replaced mechanically by a script immediately before
the agent is called. This module performs exactly that step.
"""

from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"{{\s*([A-Z0-9_]+)\s*}}")

# Repository root resolved relative to this file: src/trussflow/prompts.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = _REPO_ROOT / "docs" / "prompts"


class PromptError(RuntimeError):
    """Raised when a prompt cannot be loaded or has unfilled placeholders."""


def load_prompt(name: str, replacements: dict[str, str] | None = None) -> str:
    """Load ``docs/prompts/<name>.md`` and fill ``{{PLACEHOLDER}}`` tokens.

    Raises :class:`PromptError` if the file is missing or any placeholder is
    left unfilled, so failures are loud rather than silently shipping a broken
    prompt to the agent.
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"Prompt file not found: {path}")

    text = path.read_text(encoding="utf-8")
    replacements = replacements or {}

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in replacements:
            raise PromptError(f"Missing replacement for placeholder {{{{{key}}}}}")
        return replacements[key]

    return _PLACEHOLDER_RE.sub(_replace, text)
