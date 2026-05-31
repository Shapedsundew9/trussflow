"""Tests for prompts, schema validation, and models."""

from __future__ import annotations

import pytest

from trussflow.agents.common import AgentError, parse_json, validate
from trussflow.models import (
    Requirement,
    RequirementStatus,
    RequirementType,
    UserConcern,
)
from trussflow.prompts import PromptError, load_prompt


def test_load_prompt_fills_placeholder():
    text = load_prompt(
        "requirement-seed-writer", {"SOURCE_DOCUMENT_PATH": "docs/x.md"}
    )
    assert "docs/x.md" in text
    assert "{{" not in text


def test_load_prompt_missing_placeholder_raises():
    with pytest.raises(PromptError):
        load_prompt("requirement-seed-writer")


def test_parse_json_handles_code_fence():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_validate_rejects_bad_extraction():
    with pytest.raises(AgentError):
        validate({"requirements": [{"text": "x"}]}, "requirement_extraction")


def test_validate_accepts_good_extraction():
    payload = {
        "requirements": [
            {
                "text": "The system shall persist requirements.",
                "rationale": "Traceability.",
                "type": "Product",
                "user_concern": "High",
            }
        ]
    }
    validate(payload, "requirement_extraction")  # should not raise


def test_requirement_to_properties_roundtrip():
    req = Requirement(
        id="REQ-101",
        text="The system shall log events.",
        rationale="Transparency.",
        type=RequirementType.SYSTEM,
        status=RequirementStatus.DEFINED,
        user_concern=UserConcern.LOW,
        quality_score=0.9,
        is_atomic=True,
        is_verifiable=True,
    )
    props = req.to_properties()
    assert props["id"] == "REQ-101"
    assert props["type"] == "System"
    assert props["user_concern"] == "Low"
    assert props["quality_score"] == 0.9
