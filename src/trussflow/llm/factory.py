"""Provider selection driven by configuration."""

from __future__ import annotations

from datetime import datetime, timezone

from trussflow.config import Settings, get_logger, get_settings
from trussflow.llm.base import LLMProvider
from trussflow.llm.copilot import CopilotSession
from trussflow.llm.stub import StubProvider

logger = get_logger("llm.factory")

# One Copilot CLI session is shared across every agent invocation in a process
# run, so agents resume the same session and preserve context.
_RUN_SESSION: CopilotSession | None = None


def _run_session(settings: Settings) -> CopilotSession:
    global _RUN_SESSION
    if _RUN_SESSION is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _RUN_SESSION = CopilotSession(name=f"{settings.copilot_session_prefix}-{run_id}")
    return _RUN_SESSION


def _agent_overrides(settings: Settings, agent: str | None) -> tuple[str, str]:
    model = settings.copilot_model
    effort = settings.copilot_effort
    if agent:
        override = settings.copilot_agent_overrides.get(agent, {})
        model = override.get("model", model)
        effort = override.get("effort", effort)
    return model, effort


def get_provider(
    settings: Settings | None = None,
    *,
    agent: str | None = None,
    session: CopilotSession | None = None,
) -> LLMProvider:
    """Return the configured provider, defaulting to the offline stub.

    ``agent`` selects per-agent Copilot model/effort overrides; ``session``
    overrides the shared run session (mainly for testing).
    """
    settings = settings or get_settings()
    choice = settings.llm_provider
    if choice in ("stub", "offline", "mock"):
        logger.info("Using offline stub LLM provider")
        return StubProvider()
    if choice == "copilot":
        from trussflow.llm.copilot import CopilotProvider

        model, effort = _agent_overrides(settings, agent)
        session = session or _run_session(settings)
        logger.info(
            "Using Copilot CLI provider (agent=%s, model=%s, effort=%s)",
            agent or "default",
            model,
            effort,
        )
        return CopilotProvider(settings, session=session, model=model, effort=effort)
    raise ValueError(f"Unknown TRUSSFLOW_LLM_PROVIDER: {choice!r}")
