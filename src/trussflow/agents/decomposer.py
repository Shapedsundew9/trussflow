"""Decomposer agent: derive child requirements from a parent requirement.

Implements the layered Product -> System -> Design -> Implementation
decomposition from the vision. Given a parent requirement and a target layer,
the agent produces child requirements linked to the parent via ``CHILD_OF``.
The stub emits one clearly-derived placeholder per parent; a real LLM expands
this into several detailed children.
"""

from __future__ import annotations

import json

from trussflow.agents.common import format_requirement_id, parse_json, validate
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.stub import DERIVE_MARKER
from trussflow.models import (
    Requirement,
    RequirementStatus,
    RequirementType,
    UserConcern,
)
from trussflow.prompts import load_prompt

logger = get_logger("agents.decomposer")

_SCHEMA = "requirement_derivation"


class DecomposerAgent:
    """Derives lower-level child requirements from a parent requirement."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def build_prompt(self, parent: Requirement, target_type: RequirementType) -> str:
        # Reuse the seed-writer's quality guidance, then append the derivation
        # spec the stub reads.
        base = load_prompt(
            "requirement-seed-writer", {"SOURCE_DOCUMENT_PATH": parent.id}
        )
        spec = {
            "parent_id": parent.id,
            "parent_text": parent.text,
            "target_type": target_type.value,
            "user_concern": parent.user_concern.value,
        }
        contract = (
            "\n\n## Output Contract\n"
            "Derive the lower-level child requirements implied by the parent. "
            "Return ONLY a JSON object of the form "
            '{"requirements": [{"text", "rationale", "type", "user_concern"}]}. '
            f"Every child 'type' must be {target_type.value!r}.\n"
            f"\n{DERIVE_MARKER}\n{json.dumps(spec)}\n"
        )
        return base + contract

    def run(
        self,
        parent: Requirement,
        target_type: RequirementType,
        start_index: int,
    ) -> list[Requirement]:
        """Derive children, assigning sequential IDs from ``start_index``."""
        prompt = self.build_prompt(parent, target_type)
        response = self._provider.complete(prompt, json_mode=True)
        payload = parse_json(response.text)
        validate(payload, _SCHEMA)

        children: list[Requirement] = []
        for offset, item in enumerate(payload["requirements"]):  # type: ignore[index]
            children.append(
                Requirement(
                    id=format_requirement_id(start_index + offset),
                    text=item["text"],
                    rationale=item["rationale"],
                    type=RequirementType(item["type"]),
                    status=RequirementStatus.DEFINED,
                    user_concern=UserConcern(item["user_concern"]),
                )
            )
        logger.info(
            "Decomposer derived %d %s child requirement(s) from %s",
            len(children),
            target_type.value,
            parent.id,
        )
        return children
