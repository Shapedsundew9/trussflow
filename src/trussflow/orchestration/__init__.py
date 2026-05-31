"""Mechanical orchestration scaffolding around each agent invocation.

Implements the agent-flow described in ``docs/design/agent-flow.md``:

1. Modular pre-agent checks (``checks``) run individual pass/fail validations.
2. Failures route to a specific repair step (``repair``) before looping back.
3. Prompts are templated immediately before dispatch (``templates``).
4. The agent's returned status is verified and a scripted decision made
   (``status``): continue, repair, or abort.
5. On success a mechanical git ``add`` -> ``commit`` -> ``push`` runs
   (``git_ops``).

Prefect flows/tasks (``flows``/``tasks``) wire these stages together and give
the run history a persistence layer. The whole layer is opt-in via
``Settings.orchestration_enabled`` so the offline stub path is never affected.
"""

from trussflow.orchestration.checks import CheckResult, run_checks
from trussflow.orchestration.status import AgentStatus, Decision, decide, verify_status

__all__ = [
    "CheckResult",
    "run_checks",
    "AgentStatus",
    "Decision",
    "decide",
    "verify_status",
]
