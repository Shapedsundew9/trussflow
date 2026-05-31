"""Prefect flows and tasks that wire the orchestration stages together.

This module owns the only Prefect dependency in the package. Importing it
configures ``PREFECT_HOME`` (defaulting under ``.trussflow/`` which is
gitignored) so flow- and task-run history is persisted locally as the run
history layer, with no external Prefect server required.

The flow :func:`run_agent_step` executes the agent-flow loop for one agent:
modular pre-agent checks (with repair branch and loop-back) -> dispatch (prompt
templating happens inside the caller's dispatch closure) -> status verification
and a scripted continue/repair/abort decision -> mechanical git finalization on
success. :func:`run_pipeline` is a thin parent flow placeholder for chaining
steps.
"""

from __future__ import annotations

import os
from pathlib import Path

from trussflow.config import Settings, get_logger, get_settings

logger = get_logger("orchestration.flows")

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _configure_prefect_home() -> None:
    """Point PREFECT_HOME at a local, persistent directory before import.

    Respects an explicitly set PREFECT_HOME (e.g. tests using a tmp dir);
    otherwise derives it from ``TRUSSFLOW_PREFECT_HOME``.
    """
    if os.environ.get("PREFECT_HOME"):
        return
    configured = os.environ.get("TRUSSFLOW_PREFECT_HOME", ".trussflow/prefect")
    home = Path(configured)
    if not home.is_absolute():
        home = _REPO_ROOT / home
    home.mkdir(parents=True, exist_ok=True)
    os.environ["PREFECT_HOME"] = str(home)


def _quiet_prefect_defaults() -> None:
    """Reduce Prefect's network/log chatter for a local, single-process run."""
    os.environ.setdefault("PREFECT_LOGGING_TO_API_ENABLED", "false")
    os.environ.setdefault("PREFECT_SERVER_ANALYTICS_ENABLED", "false")
    os.environ.setdefault("PREFECT_TELEMETRY_ENABLED", "false")


_configure_prefect_home()
_quiet_prefect_defaults()

from prefect import flow, task  # noqa: E402 - must follow PREFECT_HOME setup.

from trussflow.orchestration.checks import (  # noqa: E402
    CheckResult,
    first_failure,
    run_checks,
)
from trussflow.orchestration.git_ops import GitResult, finalize  # noqa: E402
from trussflow.orchestration.repair import RepairOutcome, route_repair  # noqa: E402
from trussflow.orchestration.runner import (  # noqa: E402
    DispatchFn,
    OrchestrationAbort,
    StepContext,
    StepOutcome,
    StepResult,
)
from trussflow.orchestration.status import Decision, decide  # noqa: E402


@task(name="run-checks")
def _checks_task(agent: str, context: StepContext) -> list[CheckResult]:
    return run_checks(agent, context)


@task(name="route-repair")
def _repair_task(result: CheckResult, context: StepContext) -> RepairOutcome:
    return route_repair(result, context)


@task(name="dispatch-agent")
def _dispatch_task(dispatch: DispatchFn, context: StepContext) -> StepResult:
    return dispatch(context)


@task(name="git-finalize")
def _git_task(paths: list[str], message: str, settings: Settings) -> GitResult:
    return finalize(paths, message, settings=settings)


def _emit_artifact(outcome: StepOutcome) -> None:
    """Record a Prefect table artifact for the step (best effort)."""
    try:
        from prefect.artifacts import create_table_artifact

        rows = [
            {"stage": "check", "name": c.name, "passed": c.passed, "detail": c.message}
            for c in outcome.checks
        ]
        rows.append(
            {
                "stage": "decision",
                "name": outcome.agent,
                "passed": outcome.decision is Decision.CONTINUE,
                "detail": outcome.decision.value,
            }
        )
        rows.append(
            {
                "stage": "git",
                "name": "finalize",
                "passed": outcome.git.committed,
                "detail": outcome.git.message,
            }
        )
        create_table_artifact(
            key=f"trussflow-{outcome.agent}".lower().replace("_", "-"),
            table=rows,
            description=f"Orchestration record for agent {outcome.agent}.",
        )
    except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
        logger.debug("Could not emit Prefect artifact: %s", exc)


def _run_preagent_checks(
    agent: str, context: StepContext, *, budget: int
) -> tuple[list[CheckResult], int]:
    """Run checks, branching to repair and looping back until clean.

    Returns the final check results and the remaining repair budget. Raises
    :class:`OrchestrationAbort` when a failure is not mechanically recoverable
    or the budget is exhausted.
    """
    remaining = budget
    while True:
        results = _checks_task(agent, context)
        failure = first_failure(results)
        if failure is None:
            return results, remaining
        if remaining <= 0:
            raise OrchestrationAbort(
                f"{agent}: check '{failure.name}' failed and repair budget exhausted."
            )
        outcome = _repair_task(failure, context)
        remaining -= 1
        if not outcome.recovered:
            raise OrchestrationAbort(
                f"{agent}: check '{failure.name}' not recoverable: {outcome.message}"
            )


@flow(name="run-agent-step")
def run_agent_step(
    agent: str,
    context: StepContext,
    dispatch: DispatchFn,
    *,
    settings: Settings | None = None,
) -> StepOutcome:
    """Run the full agent-flow loop for a single agent and return its record."""
    settings = settings or get_settings()
    budget = settings.orchestration_max_repairs

    checks, remaining = _run_preagent_checks(agent, context, budget=budget)

    decision = Decision.ABORT
    result: StepResult | None = None
    while True:
        result = _dispatch_task(dispatch, context)
        decision = decide(result.status, repairs_remaining=remaining)
        if decision is Decision.CONTINUE:
            break
        if decision is Decision.ABORT:
            raise OrchestrationAbort(
                f"{agent}: status verification aborted "
                f"(error={result.status.error!r})."
            )
        remaining -= 1  # REPAIR: re-dispatch within budget.

    message = f"trussflow({agent}): {result.status.item_count} item(s)"
    git = _git_task(result.artifacts, message, settings)

    outcome = StepOutcome(
        agent=agent, checks=checks, decision=decision, result=result, git=git
    )
    _emit_artifact(outcome)
    logger.info(
        "Step %s complete: decision=%s git=%s",
        agent,
        decision.value,
        git.message,
    )
    return outcome


@flow(name="run-pipeline")
def run_pipeline(steps: list[tuple[str, StepContext, DispatchFn]]) -> list[StepOutcome]:
    """Chain several agent steps under one parent flow for shared history."""
    return [run_agent_step(agent, ctx, dispatch) for agent, ctx, dispatch in steps]
