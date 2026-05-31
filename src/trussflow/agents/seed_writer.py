"""Seed-writer agent: vision text -> candidate requirements.

Wraps the prompt in ``docs/prompts/requirement-seed-writer.md`` and appends a
machine-readable ``===SOURCE===`` block so the deterministic stub (and a real
LLM, harmlessly) can locate the source text. Output is parsed and validated
against the requirement-extraction JSON Schema before becoming model objects.
"""

from __future__ import annotations

from trussflow.agents.common import (
    format_requirement_id,
    parse_json,
    validate,
)
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import SOURCE_MARKER
from trussflow.models import Requirement, RequirementStatus, RequirementType, UserConcern
from trussflow.prompts import load_prompt

logger = get_logger("agents.seed_writer")

_SCHEMA = "requirement_extraction"


class SeedWriterAgent:
    """Authors an initial requirement baseline from a source document."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(self, source_path: str, source_text: str) -> str:
        base = load_prompt(
            "requirement-seed-writer",
            {"SOURCE_DOCUMENT_PATH": source_path},
        )
        instructions = (
            "\n\n## Output Contract\n"
            "Return ONLY a JSON object matching this shape: "
            '{"requirements": [{"text", "rationale", "type", "user_concern"}]}. '
            "'type' is one of Product, System, Design, Implementation. "
            "'user_concern' is High or Low.\n"
            f"\n{SOURCE_MARKER}\n{source_text}\n"
        )
        return base + instructions

    def run(self, source_path: str, source_text: str) -> list[Requirement]:
        prompt = self.build_prompt(source_path, source_text)
        response = self._provider.complete(prompt, json_mode=True)
        payload = parse_json(response.text)
        validate(payload, _SCHEMA)

        requirements: list[Requirement] = []
        for index, item in enumerate(payload["requirements"], start=1):  # type: ignore[index]
            requirements.append(
                Requirement(
                    id=format_requirement_id(index),
                    text=item["text"],
                    rationale=item["rationale"],
                    type=RequirementType(item["type"]),
                    status=RequirementStatus.DEFINED,
                    user_concern=UserConcern(item["user_concern"]),
                )
            )
        logger.info("Seed writer produced %d requirement(s)", len(requirements))
        return requirements
