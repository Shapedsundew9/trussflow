"""Modular pre-agent checks.

Each check is an individual, codified function that inspects the run
``context`` and returns a single :class:`CheckResult` with a clear pass/fail
outcome. Per ``docs/design/agent-flow.md`` the checks are deliberately *not*
combined into one compound validation: file-structure, document-format, and
cross-reference consistency are separate so a failure can branch to a specific
repair step before looping back.

A check never raises for an expected validation failure; it returns a failing
:class:`CheckResult` carrying the ``repair_step`` that knows how to fix it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from trussflow.agents.common import SCHEMAS_DIR
from trussflow.config import get_logger

logger = get_logger("orchestration.checks")

# A check receives the immutable run context and returns its result.
CheckContext = Mapping[str, object]
Check = Callable[[CheckContext], "CheckResult"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single pre-agent check.

    ``repair_step`` names the repair handler to route to when ``passed`` is
    False; it is ``None`` on success.
    """

    name: str
    passed: bool
    message: str
    repair_step: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "repair_step": self.repair_step,
            "details": self.details,
        }


def _ok(name: str, message: str) -> CheckResult:
    return CheckResult(name=name, passed=True, message=message)


def _fail(name: str, message: str, repair_step: str, **details: object) -> CheckResult:
    return CheckResult(
        name=name,
        passed=False,
        message=message,
        repair_step=repair_step,
        details=dict(details),
    )


# -- individual checks ----------------------------------------------------


def check_file_structure(context: CheckContext) -> CheckResult:
    """Verify the assets an agent reads/writes are correctly positioned.

    Confirms the schema directory exists and, when the agent consumes a source
    document, that the file is present on disk.
    """
    name = "file_structure"
    if not SCHEMAS_DIR.is_dir():
        return _fail(
            name,
            f"Schema directory missing: {SCHEMAS_DIR}",
            "ensure_schemas",
        )

    source_path = context.get("source_path")
    if source_path is not None:
        path = Path(str(source_path))
        if not path.is_file():
            return _fail(
                name,
                f"Source document not found: {path}",
                "locate_source_document",
                source_path=str(path),
            )
    return _ok(name, "Required files and directories are present.")


def check_document_format(context: CheckContext) -> CheckResult:
    """Verify the input document is well-formed enough to process.

    For agents that read source text, an empty or whitespace-only document
    cannot produce requirements and is routed to a repair step.
    """
    name = "document_format"
    source_text = context.get("source_text")
    if source_text is None:
        source_path = context.get("source_path")
        if source_path is not None:
            try:
                source_text = Path(str(source_path)).read_text(encoding="utf-8")
            except OSError as exc:
                return _fail(
                    name,
                    f"Source document unreadable: {exc}",
                    "locate_source_document",
                )
    if source_text is not None and not str(source_text).strip():
        return _fail(
            name,
            "Source document is empty or whitespace only.",
            "request_nonempty_source",
        )
    return _ok(name, "Document format is acceptable.")


def check_cross_references(context: CheckContext) -> CheckResult:
    """Verify referenced graph nodes exist before the agent runs.

    Agents that operate on an existing node (e.g. ``derive``/``supersede``)
    must reference a requirement that is actually present in the store.
    """
    name = "cross_references"
    store = context.get("store")
    parent_id = context.get("parent_id") or context.get("target_id")
    if store is not None and parent_id is not None:
        known = {row["id"] for row in store.list_requirements()}
        if str(parent_id) not in known:
            return _fail(
                name,
                f"Referenced requirement not in graph: {parent_id}",
                "resolve_missing_reference",
                missing_id=str(parent_id),
            )
    return _ok(name, "Cross-references are consistent.")


# -- registry -------------------------------------------------------------

# Tailored per-agent check ordering. Each agent runs only the checks that are
# meaningful for it, keeping the validations modular and context-specific.
CHECK_REGISTRY: dict[str, list[Check]] = {
    "seed_writer": [check_file_structure, check_document_format],
    "analyst": [check_file_structure],
    "feature_extractor": [check_file_structure, check_cross_references],
    "work_packager": [check_file_structure, check_cross_references],
    "decomposer": [check_file_structure, check_cross_references],
    "supersede": [check_file_structure, check_cross_references],
}


def checks_for(agent: str) -> list[Check]:
    """Return the ordered checks registered for ``agent`` (empty if unknown)."""
    return CHECK_REGISTRY.get(agent, [check_file_structure])


def run_checks(agent: str, context: CheckContext) -> list[CheckResult]:
    """Run every check registered for ``agent`` and return all results.

    All checks run so the audit trail is complete; the caller decides how to
    route the first failure to a repair step.
    """
    results = [check(context) for check in checks_for(agent)]
    for result in results:
        level = logger.info if result.passed else logger.warning
        level("check[%s/%s] -> %s", agent, result.name, result.message)
    return results


def first_failure(results: list[CheckResult]) -> CheckResult | None:
    """Return the first failing check result, or ``None`` if all passed."""
    return next((r for r in results if not r.passed), None)
