"""Tests for the modular pre-agent checks and repair routing."""

from __future__ import annotations

from trussflow.orchestration.checks import (
    CHECK_REGISTRY,
    check_cross_references,
    check_document_format,
    check_file_structure,
    first_failure,
    run_checks,
)
from trussflow.orchestration.repair import route_repair


class _Store:
    def __init__(self, ids):
        self._ids = ids

    def list_requirements(self):
        return [{"id": i} for i in self._ids]


def test_file_structure_passes_without_source():
    result = check_file_structure({})
    assert result.passed
    assert result.repair_step is None


def test_file_structure_fails_for_missing_source(tmp_path):
    missing = tmp_path / "nope.md"
    result = check_file_structure({"source_path": str(missing)})
    assert not result.passed
    assert result.repair_step == "locate_source_document"


def test_document_format_flags_empty_source():
    result = check_document_format({"source_text": "   \n  "})
    assert not result.passed
    assert result.repair_step == "request_nonempty_source"


def test_document_format_accepts_text():
    assert check_document_format({"source_text": "The system shall persist."}).passed


def test_cross_references_detects_missing_parent():
    store = _Store(["REQ-100"])
    result = check_cross_references({"store": store, "parent_id": "REQ-999"})
    assert not result.passed
    assert result.repair_step == "resolve_missing_reference"


def test_cross_references_passes_for_known_parent():
    store = _Store(["REQ-100"])
    assert check_cross_references({"store": store, "parent_id": "REQ-100"}).passed


def test_registry_runs_tailored_checks():
    results = run_checks("seed_writer", {"source_text": "The system shall log in."})
    names = {r.name for r in results}
    assert names == {"file_structure", "document_format"}
    assert first_failure(results) is None


def test_every_known_agent_is_registered():
    for agent in (
        "seed_writer",
        "analyst",
        "feature_extractor",
        "work_packager",
        "decomposer",
        "supersede",
    ):
        assert agent in CHECK_REGISTRY


def test_route_repair_for_missing_source_is_unrecoverable(tmp_path):
    missing = tmp_path / "nope.md"
    result = check_file_structure({"source_path": str(missing)})
    outcome = route_repair(result, {"source_path": str(missing)})
    assert outcome.recovered is False
    assert outcome.repair_step == "locate_source_document"


def test_route_repair_unknown_step_aborts():
    from trussflow.orchestration.checks import CheckResult

    bogus = CheckResult("x", passed=False, message="m", repair_step="does_not_exist")
    outcome = route_repair(bogus, {})
    assert outcome.recovered is False
