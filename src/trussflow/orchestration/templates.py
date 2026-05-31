"""Prompt templating for the orchestration wrapper.

Per ``docs/design/agent-flow.md`` the agent prompt is built from a preformatted
template whose ``{{PLACEHOLDER}}`` tokens are mechanically substituted
immediately before dispatch. This is a thin layer over
:func:`trussflow.prompts.load_prompt` so the substitution logic stays in one
place; the orchestration flow calls :func:`render_prompt` right before handing
the prompt to the agent/provider.
"""

from __future__ import annotations

from trussflow.config import get_logger
from trussflow.prompts import load_prompt

logger = get_logger("orchestration.templates")

# Maps each agent to the prompt template file under ``docs/prompts``.
PROMPT_TEMPLATES: dict[str, str] = {
    "seed_writer": "requirement-seed-writer",
    "analyst": "requirement-analyst",
}


def render_prompt(agent: str, replacements: dict[str, str] | None = None) -> str:
    """Render the prompt template registered for ``agent``.

    Raises :class:`trussflow.prompts.PromptError` (via ``load_prompt``) if the
    template is missing or a placeholder is left unfilled, so a broken prompt is
    never dispatched.
    """
    template = PROMPT_TEMPLATES.get(agent, agent)
    logger.info("Rendering prompt template %r for agent %s", template, agent)
    return load_prompt(template, replacements)
