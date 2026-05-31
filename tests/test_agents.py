"""Tests for the deterministic stub provider and agents."""

from __future__ import annotations

import json

from trussflow.agents.analyst import AnalystAgent
from trussflow.agents.seed_writer import SeedWriterAgent
from trussflow.llm.stub import StubProvider
from trussflow.models import RequirementType, UserConcern

VISION_TEXT = (
    "The system must persist every requirement for future access. "
    "Security of user data is a top priority for the founders. "
    "The application should let founders review proposed solutions."
)


def test_stub_extracts_requirements_as_shall():
    agent = SeedWriterAgent(StubProvider())
    reqs = agent.run("vision.md", VISION_TEXT)
    assert reqs, "expected at least one requirement"
    for req in reqs:
        assert "shall" in req.text.lower()
        assert req.type is RequirementType.PRODUCT


def test_stub_marks_security_as_high_concern():
    agent = SeedWriterAgent(StubProvider())
    reqs = agent.run("vision.md", VISION_TEXT)
    security = [r for r in reqs if "security" in r.text.lower()]
    assert security
    assert all(r.user_concern is UserConcern.HIGH for r in security)


def test_stub_extraction_is_deterministic():
    agent = SeedWriterAgent(StubProvider())
    first = [r.text for r in agent.run("vision.md", VISION_TEXT)]
    second = [r.text for r in agent.run("vision.md", VISION_TEXT)]
    assert first == second


def test_analyst_grades_each_requirement():
    seed = SeedWriterAgent(StubProvider())
    reqs = seed.run("vision.md", VISION_TEXT)
    analyst = AnalystAgent(StubProvider())
    grades = analyst.run(reqs)
    assert len(grades) == len(reqs)
    for grade in grades:
        assert 0.0 <= grade.quality_score <= 1.0
        assert isinstance(grade.is_atomic, bool)
        assert isinstance(grade.is_verifiable, bool)


def test_analyst_flags_missing_shall():
    provider = StubProvider()
    prompt = (
        "===REQUIREMENTS_JSON===\n"
        + json.dumps([{"id": "REQ-100", "text": "The system is robust and fast."}])
    )
    payload = json.loads(provider.complete(prompt).text)
    grade = payload["grades"][0]
    assert grade["quality_score"] < 1.0
    assert any("SHALL" in f["rule"] for f in grade["findings"])
