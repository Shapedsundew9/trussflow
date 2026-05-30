"""Tests for schema-level requirement validation."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.validation.schema_validation import (
    load_amendment_schema,
    load_errata_schema,
    load_schema,
    validate_amendment_file,
    validate_errata_file,
    validate_requirement_file,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def test_schema_validation_accepts_valid_entry(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps(
            {
                "ruid": "A",
                "rl": 0,
                "rs": "c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define one top-level requirement.",
                "rationale": "This creates a valid root node.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    entries, issues = validate_requirement_file(requirement_file, load_schema())

    assert len(entries) == 1
    assert issues == []


def test_schema_validation_accepts_descendant_array_file(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "A" / "A.json"
    _write(
        requirement_file,
        json.dumps(
            [
                {
                    "ruid": "A0",
                    "rl": 1,
                    "rs": "c",
                    "timestamp": "2026-05-30T12:10:00Z",
                    "text": "The system shall define one valid child requirement.",
                    "rationale": "This establishes hierarchy for validation.",
                    "scope": "in",
                    "refs": {
                        "depends_on": [],
                        "related_to": [],
                        "supersedes": [],
                    },
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    entries, issues = validate_requirement_file(requirement_file, load_schema())

    assert len(entries) == 1
    assert entries[0]["ruid"] == "A0"
    assert issues == []


def test_schema_validation_rejects_unknown_field(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps(
            {
                "ruid": "A",
                "rl": 0,
                "rs": "c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define one top-level requirement.",
                "rationale": "This creates a valid root node.",
                "scope": "in",
                "extra_field": "not_allowed",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "schema" for issue in issues)


def test_schema_validation_rejects_root_array_document(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps([{"ruid": "A"}], indent=2) + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "file.shape" for issue in issues)


def test_schema_validation_rejects_descendant_non_array_document(
    tmp_path: Path,
) -> None:
    requirement_file = tmp_path / "requirements" / "A" / "A.json"
    _write(
        requirement_file,
        json.dumps({"ruid": "A0"}, indent=2) + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "file.shape" for issue in issues)


def test_schema_validation_rejects_malformed_json(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        '{"ruid": "A", "timestamp": "2026-05-30T12:00:00Z",',
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "file.parse" for issue in issues)


def test_schema_validation_rejects_wrong_json_scalar_types(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps(
            {
                "ruid": "A",
                "rl": "0",
                "rs": 1,
                "timestamp": "2026-05-30T12:00:00Z",
                "text": 123,
                "rationale": "This creates a valid root node.",
                "scope": True,
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "schema" for issue in issues)
    assert any("text" in issue.message for issue in issues)
    assert any("scope" in issue.message for issue in issues)


def test_errata_schema_validation_accepts_valid_entry(tmp_path: Path) -> None:
    errata_file = tmp_path / "errata" / "batch-001.json"
    _write(
        errata_file,
        json.dumps(
            [
                {
                    "errata_id": "ERR-A-20260530T120000Z",
                    "discovered_timestamp": "2026-05-30T12:00:00Z",
                    "analyst_id": "agent.requirement-analyst",
                    "error_type": "gap",
                    "description": "A child requirement is missing for published scope handling.",
                    "affected_ruids": ["A"],
                    "violated_rule": "text.verifiability",
                    "root_cause": "The statement is too broad for verification.",
                    "solutions": [
                        {
                            "solution_id": "primary",
                            "action_type": "create_requirement",
                            "description": "Create a child with measurable acceptance criteria.",
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    entries, issues = validate_errata_file(errata_file, load_errata_schema())

    assert len(entries) == 1
    assert issues == []


def test_errata_schema_validation_rejects_non_array_document(tmp_path: Path) -> None:
    errata_file = tmp_path / "errata" / "batch-001.json"
    _write(
        errata_file,
        json.dumps(
            {
                "errata_id": "ERR-A-20260530T120000Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _, issues = validate_errata_file(errata_file, load_errata_schema())

    assert issues
    assert any(issue.rule == "file.shape" for issue in issues)


def test_amendment_schema_validation_accepts_valid_entry(tmp_path: Path) -> None:
    amendment_file = tmp_path / "amendments" / "batch-001.json"
    _write(
        amendment_file,
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-A-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "rationale": "Primary solution keeps hierarchy stable.",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                            "parent_ruid": "A",
                            "new_ruid": "AB",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Ensures verifiable decomposition.",
                                "scope": "in",
                                "rl": 1,
                                "rs": "p",
                                "refs": {
                                    "depends_on": [],
                                    "related_to": [],
                                    "supersedes": [],
                                },
                            },
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    entries, issues = validate_amendment_file(amendment_file, load_amendment_schema())

    assert len(entries) == 1
    assert issues == []


def test_amendment_schema_validation_rejects_missing_action_operands(
    tmp_path: Path,
) -> None:
    amendment_file = tmp_path / "amendments" / "batch-001.json"
    _write(
        amendment_file,
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-A-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _, issues = validate_amendment_file(amendment_file, load_amendment_schema())

    assert issues
    assert any(issue.rule == "schema" for issue in issues)
