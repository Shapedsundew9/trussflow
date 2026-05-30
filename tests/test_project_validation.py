"""Tests for project-wide requirement validation rules."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.validation import validate_requirements_tree


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
