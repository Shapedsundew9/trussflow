"""Work-packager agent: requirements -> execution-level work packages.

Each work package implements exactly one requirement (``IMPLEMENTS`` edge). The
scope (``Human`` vs ``AI_Autonomous``) reflects the requirement's user concern:
low-concern requirements may be executed autonomously by an AI builder.
"""

from __future__ import annotations

import json

from trussflow.agents.common import (
    AgentError,
    format_workpackage_id,
    parse_json,
    validate,
)
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import WORKPACKAGE_MARKER
from trussflow.models import Requirement, WorkPackage, WorkPackageScope

logger = get_logger("agents.work_packager")

_SCHEMA = "workpackage_generation"

_INSTRUCTIONS = (
    "You are a delivery planner. For each requirement, write one actionable "
    "work package that implements it. Set 'scope' to 'AI_Autonomous' when the "
    "requirement is low user-concern, otherwise 'Human'.\n\n"
    "## Output Contract\n"
    "Return ONLY a JSON object of the form "
    '{"work_packages": [{"requirement_id", "summary", "scope"}]}. '
    "Use the exact requirement_id values provided."
)


class WorkPackagerAgent:
    """Generates work packages that implement requirements."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(self, requirements: list[Requirement]) -> str:
        payload = [
            {"id": r.id, "text": r.text, "user_concern": r.user_concern.value}
            for r in requirements
        ]
        return f"{_INSTRUCTIONS}\n\n{WORKPACKAGE_MARKER}\n{json.dumps(payload)}\n"

    def run(self, requirements: list[Requirement]) -> list[tuple[WorkPackage, str]]:
        """Return ``(work_package, requirement_id)`` pairs for IMPLEMENTS edges."""
        if not requirements:
            return []
        prompt = self.build_prompt(requirements)
        response = self._provider.complete(prompt, json_mode=True)
        payload = parse_json(response.text)
        validate(payload, _SCHEMA)

        valid_ids = {r.id for r in requirements}
        results: list[tuple[WorkPackage, str]] = []
        for index, item in enumerate(payload["work_packages"], start=1):  # type: ignore[index]
            req_id = item["requirement_id"]
            if req_id not in valid_ids:
                raise AgentError(
                    f"Work package references unknown requirement {req_id!r}."
                )
            work_package = WorkPackage(
                id=format_workpackage_id(index),
                summary=item["summary"],
                scope=WorkPackageScope(item["scope"]),
            )
            results.append((work_package, req_id))
        logger.info("Work packager produced %d work package(s)", len(results))
        return results
