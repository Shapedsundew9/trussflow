"""Shared orchestration types and the dispatch contract.

These types are deliberately free of any Prefect import so the core pipeline
can build a dispatch closure and run it directly on the offline path without
pulling in the workflow engine. The Prefect flow in ``flows`` consumes the same
types when orchestration is enabled.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from trussflow.orchestration.checks import CheckResult
from trussflow.orchestration.git_ops import GitResult
from trussflow.orchestration.status import AgentStatus, Decision

# The run context passed through checks, repair, and dispatch.
StepContext = Mapping[str, Any]


class OrchestrationAbort(RuntimeError):
    """Raised when a step cannot proceed (failed checks or aborted status)."""


@dataclass
class StepResult:
    """What a dispatch closure returns after running an agent and persisting.

    ``value`` is the object the wrapped pipeline function should return to its
    caller (e.g. a ``list[Requirement]`` or an ``int``). ``status`` is the
    verified envelope; ``artifacts`` are paths to commit on success.
    """

    value: Any
    status: AgentStatus
    artifacts: list[str] = field(default_factory=list)


# A dispatch renders the prompt, runs the agent, persists, and reports a result.
DispatchFn = Callable[[StepContext], StepResult]


@dataclass
class StepOutcome:
    """Full record of an orchestrated step for auditing."""

    agent: str
    checks: list[CheckResult]
    decision: Decision
    result: StepResult
    git: GitResult

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "checks": [c.to_dict() for c in self.checks],
            "decision": self.decision.value,
            "status": self.result.status.to_dict(),
            "artifacts": list(self.result.artifacts),
            "git": self.git.to_dict(),
        }
