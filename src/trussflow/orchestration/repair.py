"""Repair steps that a failed pre-agent check can branch to.

Each :class:`~trussflow.orchestration.checks.CheckResult` failure names a
``repair_step``. :func:`route_repair` looks that name up in
:data:`REPAIR_REGISTRY` and runs the handler, which attempts a mechanical fix
and reports whether the flow should loop back and re-run the checks.

Handlers are intentionally conservative: when a problem cannot be fixed
mechanically (e.g. a missing source document) the handler returns a
non-recoverable :class:`RepairOutcome` so the flow aborts rather than looping
forever. The per-step retry budget is enforced by the calling Prefect flow.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from trussflow.agents.common import SCHEMAS_DIR
from trussflow.config import get_logger
from trussflow.orchestration.checks import CheckResult

logger = get_logger("orchestration.repair")

RepairContext = Mapping[str, object]


@dataclass(frozen=True)
class RepairOutcome:
    """Result of attempting a repair.

    ``recovered`` True means the flow should loop back and re-run checks;
    False means the issue is not mechanically fixable and the flow must abort.
    """

    repair_step: str
    recovered: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "repair_step": self.repair_step,
            "recovered": self.recovered,
            "message": self.message,
        }


def _ensure_schemas(_context: RepairContext) -> RepairOutcome:
    """Schemas ship with the package; their absence is unrecoverable."""
    recovered = SCHEMAS_DIR.is_dir()
    return RepairOutcome(
        "ensure_schemas",
        recovered,
        "Schema directory present." if recovered else f"Cannot recreate {SCHEMAS_DIR}.",
    )


def _locate_source_document(context: RepairContext) -> RepairOutcome:
    """A missing source document cannot be synthesized mechanically."""
    source_path = context.get("source_path")
    return RepairOutcome(
        "locate_source_document",
        False,
        f"Source document must be supplied by the caller: {source_path!r}.",
    )


def _request_nonempty_source(_context: RepairContext) -> RepairOutcome:
    """An empty source needs human input; not mechanically recoverable."""
    return RepairOutcome(
        "request_nonempty_source",
        False,
        "Source document is empty; a non-empty document is required.",
    )


def _resolve_missing_reference(context: RepairContext) -> RepairOutcome:
    """A reference to a non-existent node cannot be invented."""
    missing = context.get("parent_id") or context.get("target_id")
    return RepairOutcome(
        "resolve_missing_reference",
        False,
        f"Referenced node {missing!r} does not exist in the graph.",
    )


RepairHandler = Callable[[RepairContext], RepairOutcome]

REPAIR_REGISTRY: dict[str, RepairHandler] = {
    "ensure_schemas": _ensure_schemas,
    "locate_source_document": _locate_source_document,
    "request_nonempty_source": _request_nonempty_source,
    "resolve_missing_reference": _resolve_missing_reference,
}


def route_repair(result: CheckResult, context: RepairContext) -> RepairOutcome:
    """Route a failed check to its repair handler and run it.

    Falls back to a non-recoverable outcome when no handler is registered, so
    an unknown failure can never silently loop.
    """
    step = result.repair_step or ""
    handler = REPAIR_REGISTRY.get(step)
    if handler is None:
        logger.warning("No repair handler for step %r; aborting.", step)
        return RepairOutcome(step or "unknown", False, f"No repair for {step!r}.")
    outcome = handler(context)
    level = logger.info if outcome.recovered else logger.warning
    level("repair[%s] -> %s", outcome.repair_step, outcome.message)
    return outcome
