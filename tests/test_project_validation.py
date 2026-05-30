"""Tests for project-wide requirement validation rules."""

from __future__ import annotations

from pathlib import Path

from trussflow.validation import validate_requirements_tree


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def _create_valid_tree(base: Path) -> Path:
    requirements = base / "requirements"

    _write(
        requirements / "root.yaml",
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: The product SHALL define a valid root requirement.
  rationale: This is the top-level requirement.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip()
        + "\n",
    )

    _write(
        requirements / "A" / "sA0c.yaml",
        """
- ruid: sAB1c
  timestamp: 2026-05-30T12:10:00Z
  text: The system SHALL define one valid child requirement.
  rationale: This establishes hierarchy for validation.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip()
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
        requirements / "A" / "sA0c.yaml",
        """
- ruid: sAB1c
  timestamp: 2026-05-30T12:10:00Z
  text: The system SHALL define one valid child requirement.
  rationale: This establishes hierarchy for validation.
  scope: in
  refs:
    depends_on: [sZZ1c]
    related_to: []
    supersedes: []
""".strip()
        + "\n",
    )

    issues = validate_requirements_tree(requirements)

    assert any(issue.rule == "refs.exists" for issue in issues)


def test_project_validation_detects_duplicate_rn(tmp_path: Path) -> None:
    requirements = _create_valid_tree(tmp_path)
    _write(
        requirements / "root.yaml",
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: The product SHALL define a valid root requirement.
  rationale: This is the top-level requirement.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
- ruid: mA1p
  timestamp: 2026-05-30T12:01:00Z
  text: The product MAY define a duplicate RN requirement.
  rationale: This should fail RN uniqueness.
  scope: out
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip()
        + "\n",
    )

    issues = validate_requirements_tree(requirements)

    assert any(issue.rule == "rn.unique" for issue in issues)
