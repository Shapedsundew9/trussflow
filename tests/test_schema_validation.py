"""Tests for schema-level requirement validation."""

from __future__ import annotations

from pathlib import Path

import yaml

from trussflow.validation.schema_validation import (
    load_schema,
    validate_requirement_file,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def test_schema_validation_accepts_valid_entry(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.yaml"
    _write(
        requirement_file,
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: The product SHALL define one top-level requirement.
  rationale: This creates a valid root node.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip() + "\n",
    )

    entries, issues = validate_requirement_file(requirement_file, load_schema())

    assert len(entries) == 1
    assert issues == []


def test_schema_validation_rejects_unknown_field(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.yaml"
    _write(
        requirement_file,
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: The product SHALL define one top-level requirement.
  rationale: This creates a valid root node.
  scope: in
  extra_field: not_allowed
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip() + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "schema" for issue in issues)


def test_schema_validation_rejects_non_list_document(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.yaml"
    _write(
        requirement_file,
        """
ruid: sA0c
timestamp: 2026-05-30T12:00:00Z
text: Bad shape document.
rationale: Top-level object is invalid.
scope: in
refs:
  depends_on: []
  related_to: []
  supersedes: []
""".strip() + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "file.shape" for issue in issues)


def test_custom_loader_does_not_mutate_global_safeloader() -> None:
    tags = {
        tag
        for _, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
        for tag, _ in resolvers
    }

    assert "tag:yaml.org,2002:timestamp" in tags


def test_schema_validation_flags_yaml_scalar_coercion(tmp_path: Path) -> None:
    requirement_file = tmp_path / "requirements" / "root.yaml"
    _write(
        requirement_file,
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: 123
  rationale: This creates a valid root node.
  scope: on
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip() + "\n",
    )

    _, issues = validate_requirement_file(requirement_file, load_schema())

    assert issues
    assert any(issue.rule == "yaml.scalar_coercion" for issue in issues)
    assert any("Field 'text'" in issue.message for issue in issues)
    assert any("Field 'scope'" in issue.message for issue in issues)
