"""Post-agent status verification and the scripted next-action decision.

After an agent runs, the orchestration wrapper builds an :class:`AgentStatus`
envelope, verifies it is well-formed against ``schemas/agent_status.schema.json``
(reusing the JSON-schema validation already used by the agents), and then makes
a mechanical :class:`Decision`: continue, repair, or abort.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from trussflow.agents.common import AgentError, validate
from trussflow.config import get_logger

logger = get_logger("orchestration.status")

_STATUS_SCHEMA = "agent_status"


class Decision(str, Enum):
    """Scripted next action after a verified agent status."""

    CONTINUE = "continue"
    REPAIR = "repair"
    ABORT = "abort"


@dataclass(frozen=True)
class AgentStatus:
    """Mechanical envelope describing the outcome of an agent dispatch."""

    agent: str
    schema: str
    ok: bool
    item_count: int
    validated: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "schema": self.schema,
            "ok": self.ok,
            "item_count": self.item_count,
            "validated": self.validated,
            "error": self.error,
        }


def verify_status(status: AgentStatus) -> bool:
    """Validate the status envelope against its JSON schema.

    Returns True when the envelope is well-formed and reports success;
    returns False otherwise. Raises :class:`AgentError` only when the envelope
    itself is structurally invalid (a programming error, not an agent fault).
    """
    validate(status.to_dict(), _STATUS_SCHEMA)
    return status.ok and status.validated


def decide(status: AgentStatus, *, repairs_remaining: int) -> Decision:
    """Make the scripted next-action decision from a verified status.

    - Well-formed, validated, and non-empty -> CONTINUE.
    - Recoverable (validated but empty, or a soft error) with retry budget
      left -> REPAIR.
    - Malformed/invalid output, or no retries remaining -> ABORT.
    """
    try:
        well_formed = verify_status(status)
    except AgentError as exc:
        logger.error("Status envelope malformed for %s: %s", status.agent, exc)
        return Decision.ABORT

    if well_formed and status.item_count > 0:
        return Decision.CONTINUE

    if not status.validated:
        # The agent output failed schema validation: not recoverable by retry.
        logger.warning("Agent %s output failed validation; aborting.", status.agent)
        return Decision.ABORT

    if repairs_remaining > 0:
        logger.info(
            "Agent %s produced no usable items; routing to repair (%d left).",
            status.agent,
            repairs_remaining,
        )
        return Decision.REPAIR

    logger.warning("Agent %s exhausted repair budget; aborting.", status.agent)
    return Decision.ABORT
