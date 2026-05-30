"""Tests for project-wide requirement validation rules."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.validation import validate_change_artifacts, validate_requirements_tree


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def _create_valid_tree(base: Path) -> Path:
    requirements = base / "requirements"

    _write(
        requirements / "root.json",
        json.dumps(
            {
                "ruid": "A0c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define a valid root requirement.",
                "rationale": "This is the top-level requirement.",
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

    _write(
        requirements / "A" / "AB1c.json",
        json.dumps(
            {
                "ruid": "AB1c",
                "timestamp": "2026-05-30T12:10:00Z",
                "text": "The system shall define one valid child requirement.",
                "rationale": "This establishes hierarchy for validation.",
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

    return requirements


def test_project_validation_accepts_valid_tree(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)

    issues = validate_requirements_tree(requirements)

    assert issues == []


def test_project_validation_detects_missing_reference(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    _write(
        requirements / "A" / "AB1c.json",
        json.dumps(
            {
                "ruid": "AB1c",
                "timestamp": "2026-05-30T12:10:00Z",
                "text": "The system shall define one valid child requirement.",
                "rationale": "This establishes hierarchy for validation.",
                "scope": "in",
                "refs": {
                    "depends_on": ["ZZ1c"],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    issues = validate_requirements_tree(requirements)

    assert any(issue.rule == "refs.exists" for issue in issues)


def test_project_validation_detects_duplicate_rn(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    _write(
        requirements / "A1p.json",
        json.dumps(
            {
                "ruid": "A1p",
                "timestamp": "2026-05-30T12:01:00Z",
                "text": "The product shall define a duplicate RN requirement.",
                "rationale": "This should fail RN uniqueness.",
                "scope": "out",
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

    issues = validate_requirements_tree(requirements)

    assert any(issue.rule == "rn.unique" for issue in issues)


def test_project_validation_detects_normative_may_in_text(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    _write(
        requirements / "A" / "AB1c.json",
        json.dumps(
            {
                "ruid": "AB1c",
                "timestamp": "2026-05-30T12:10:00Z",
                "text": "The system may define one valid child requirement.",
                "rationale": "This violates the NASA wording convention for requirements.",
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

    issues = validate_requirements_tree(requirements)

    assert any(issue.rule == "text.normative_may" for issue in issues)


def _create_valid_errata_and_amendments(base: Path) -> tuple[Path, Path]:
    errata_dir = base / "errata"
    amendments_dir = base / "amendments"

    _write(
        errata_dir / "batch-001.json",
        json.dumps(
            [
                {
                    "errata_id": "ERR-A-20260530T120000Z",
                    "discovered_timestamp": "2026-05-30T12:00:00Z",
                    "analyst_id": "agent.requirement-analyst",
                    "error_type": "gap",
                    "description": "A measurable child requirement is missing.",
                    "affected_ruids": ["A0c"],
                    "violated_rule": "text.verifiability",
                    "root_cause": "Current text is not measurable.",
                    "solutions": [
                        {
                            "solution_id": "primary",
                            "action_type": "create_requirement",
                            "description": "Create measurable child requirement.",
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _write(
        amendments_dir / "batch-001.json",
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-A-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "rationale": "Chosen for minimal disruption.",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                            "parent_ruid": "A0c",
                            "new_ruid": "AC1p",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Supports verifiability.",
                                "scope": "in",
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

    return errata_dir, amendments_dir


def test_change_validation_accepts_valid_artifacts(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert issues == []


def test_change_validation_detects_unknown_errata_reference(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    _write(
        amendments_dir / "batch-001.json",
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-Z-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                            "parent_ruid": "A0c",
                            "new_ruid": "AC1p",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Supports verifiability.",
                                "scope": "in",
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

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert any(issue.rule == "amendment.errata.exists" for issue in issues)


def test_change_validation_blocks_in_place_published_edit(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    _write(
        amendments_dir / "batch-001.json",
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
                            "action": "scope_change",
                            "target_ruid": "A0c",
                            "new_state": {
                                "scope": "out",
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

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert any(issue.rule == "amendment.immutable_published" for issue in issues)


def test_change_validation_detects_supersede_timestamp_not_newer(
    tmp_path: Path,
) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    _write(
        amendments_dir / "batch-001.json",
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
                            "action": "supersede",
                            "target_ruid": "AB1c",
                            "new_ruid": "AC1c",
                            "new_timestamp": "2026-05-30T12:09:00Z",
                            "supersedes": ["AB1c"],
                            "new_state": {
                                "text": "The system shall define measurable verification criteria.",
                                "rationale": "Supersedes older requirement text.",
                                "scope": "in",
                                "refs": {
                                    "depends_on": [],
                                    "related_to": [],
                                    "supersedes": ["AB1c"],
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

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert any(issue.rule == "amendment.supersedes.older" for issue in issues)


def test_change_validation_detects_create_invalid_direct_child(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    _write(
        amendments_dir / "batch-001.json",
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
                            "parent_ruid": "A0c",
                            "new_ruid": "ABC1p",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Supports verifiability.",
                                "scope": "in",
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

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert any(issue.rule == "amendment.create.hierarchy" for issue in issues)


def test_change_validation_detects_invalid_state_transition(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    errata_dir, amendments_dir = _create_valid_errata_and_amendments(tmp_path)

    _write(
        amendments_dir / "batch-001.json",
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
                            "action": "state_transition",
                            "target_ruid": "AB1c",
                            "new_state": {
                                "rs": "p",
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

    issues = validate_change_artifacts(requirements, errata_dir, amendments_dir)

    assert any(issue.rule == "amendment.state_transition.demotion" for issue in issues)
