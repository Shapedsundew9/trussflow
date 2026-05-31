"""Tests for Phase 3 decomposition: features, work packages, derivation."""

from __future__ import annotations

from trussflow.agents.decomposer import DecomposerAgent
from trussflow.agents.feature_extractor import FeatureExtractorAgent
from trussflow.agents.work_packager import WorkPackagerAgent
from trussflow.llm.stub import StubProvider
from trussflow.models import (
    Requirement,
    RequirementType,
    UserConcern,
    WorkPackageScope,
)

VISION_MD = (
    "# Project\n\n"
    "## Knowledge Graph\n"
    "The system shall persist requirements.\n\n"
    "## Security\n"
    "Security of user data is a top priority.\n"
)


def test_feature_extractor_uses_headings():
    agent = FeatureExtractorAgent(StubProvider())
    features = agent.run(VISION_MD)
    names = {f.name for f in features}
    assert "Knowledge Graph" in names
    assert "Security" in names
    assert all(f.id.startswith("FEAT-") for f in features)


def test_feature_extractor_falls_back_when_no_headings():
    agent = FeatureExtractorAgent(StubProvider())
    features = agent.run("No headings here, just prose about the system.")
    assert len(features) == 1
    assert features[0].name == "Core Capability"


def _requirements() -> list[Requirement]:
    return [
        Requirement(
            id="REQ-101",
            text="The system shall persist requirements.",
            rationale="Traceability.",
            type=RequirementType.PRODUCT,
            user_concern=UserConcern.LOW,
        ),
        Requirement(
            id="REQ-102",
            text="The system shall encrypt user data.",
            rationale="Security.",
            type=RequirementType.PRODUCT,
            user_concern=UserConcern.HIGH,
        ),
    ]


def test_work_packager_scopes_by_concern():
    agent = WorkPackagerAgent(StubProvider())
    pairs = agent.run(_requirements())
    by_req = {req_id: wp for wp, req_id in pairs}
    assert by_req["REQ-101"].scope is WorkPackageScope.AI_AUTONOMOUS
    assert by_req["REQ-102"].scope is WorkPackageScope.HUMAN
    assert all(wp.id.startswith("WP-") for wp, _ in pairs)


def test_decomposer_assigns_sequential_ids_and_target_type():
    parent = _requirements()[0]
    agent = DecomposerAgent(StubProvider())
    children = agent.run(parent, RequirementType.SYSTEM, start_index=10)
    assert children
    assert all(c.type is RequirementType.SYSTEM for c in children)
    assert children[0].id == "REQ-110"


def test_decomposer_child_text_references_parent():
    parent = _requirements()[0]
    agent = DecomposerAgent(StubProvider())
    children = agent.run(parent, RequirementType.SYSTEM, start_index=10)
    assert "persist requirements" in children[0].text.lower()
