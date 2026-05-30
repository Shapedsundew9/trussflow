"""Tests for schema-level requirement validation."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.validation.schema_validation import (
    load_schema,
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
                "ruid": "A0c",
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


def test_schema_validation_rejects_unknown_field(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps(
            {
                "ruid": "A0c",
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


def test_schema_validation_rejects_non_object_document(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        json.dumps([{"ruid": "A0c"}], indent=2) + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "file.shape" for issue in issues)


def test_schema_validation_rejects_malformed_json(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.json"
    _write(
        requirement_file,
        '{"ruid": "A0c", "timestamp": "2026-05-30T12:00:00Z",',
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
                "ruid": "A0c",
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
