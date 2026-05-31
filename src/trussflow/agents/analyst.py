"""Analyst agent: grades candidate requirements for quality.

Wraps ``docs/prompts/requirement-analyst.md`` and appends a machine-readable
``===REQUIREMENTS_JSON===`` block listing the requirements under review. Output
is validated against the grading JSON Schema and aligned positionally with the
input requirements.
"""

from __future__ import annotations

import json

from trussflow.agents.common import AgentError, parse_json, validate
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import REQUIREMENTS_MARKER
from trussflow.models import Finding, Grade, Requirement
from trussflow.prompts import load_prompt

logger = get_logger("agents.analyst")

_SCHEMA = "requirement_grading"


class AnalystAgent:
    """Reviews candidate requirements and returns per-requirement grades."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(self, requirements: list[Requirement]) -> str:
        base = load_prompt("requirement-analyst")
        payload = [
            {"id": r.id, "text": r.text, "rationale": r.rationale}
            for r in requirements
        ]
        instructions = (
            "\n\n## Output Contract\n"
            "Return ONLY a JSON object of the form "
            '{"grades": [{"quality_score", "is_atomic", "is_verifiable", '
            '"findings": [...]}]}. Provide one grade per requirement, in the '
            "same order as given. 'quality_score' is between 0 and 1.\n"
            f"\n{REQUIREMENTS_MARKER}\n{json.dumps(payload)}\n"
        )
        return base + instructions

    def run(self, requirements: list[Requirement]) -> list[Grade]:
        if not requirements:
            return []
        prompt = self.build_prompt(requirements)
        response = self._provider.complete(prompt, json_mode=True)
        payload = parse_json(response.text)
        validate(payload, _SCHEMA)

        raw_grades = payload["grades"]  # type: ignore[index]
        if len(raw_grades) != len(requirements):
            raise AgentError(
                f"Analyst returned {len(raw_grades)} grades for "
                f"{len(requirements)} requirements."
            )

        grades: list[Grade] = []
        for requirement, item in zip(requirements, raw_grades):
            findings = [
                Finding(
                    requirement_id=requirement.id,
                    issue=f["issue"],
                    rule=f["rule"],
                    suggested_fix=f["suggested_fix"],
                    severity=f.get("severity", "medium"),
                )
                for f in item.get("findings", [])
            ]
            grades.append(
                Grade(
                    requirement_id=requirement.id,
                    quality_score=float(item["quality_score"]),
                    is_atomic=bool(item["is_atomic"]),
                    is_verifiable=bool(item["is_verifiable"]),
                    findings=findings,
                )
            )
        logger.info("Analyst graded %d requirement(s)", len(grades))
        return grades
