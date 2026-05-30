"""Schema-based validation for Trussflow requirement files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(slots=True)
class ValidationIssue:
    """Structured validation issue for schema or semantic checks."""

    rule: str
    message: str
    file_path: str
    entry_index: int | None = None
    ruid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "error_code": self.rule,
            "rule": self.rule,
            "message": self.message,
            "file_path": self.file_path,
        }
        if self.entry_index is not None:
            data["entry_index"] = self.entry_index
        if self.ruid is not None:
            data["ruid"] = self.ruid
        return data


def default_schema_path() -> Path:
    """Return the repository-local path to requirement schema."""

    return Path(__file__).resolve().parents[3] / "schemas" / "requirement.schema.json"


def load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    """Load and parse the JSON Schema document."""

    target = schema_path or default_schema_path()
    return json.loads(target.read_text(encoding="utf-8"))


def load_requirement_file(
    file_path: Path,
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    """Load one JSON requirement object and return it as a single-entry list."""

    issues: list[ValidationIssue] = []

    try:
        raw_bytes = file_path.read_bytes()
    except OSError as exc:
        return [], [
            ValidationIssue(
                rule="file.read",
                message=f"Unable to read file: {exc}",
                file_path=str(file_path),
            )
        ]

    try:
        text = raw_bytes.decode("ascii")
    except UnicodeDecodeError:
        return [], [
            ValidationIssue(
                rule="file.ascii",
                message="Requirement JSON must be ASCII.",
                file_path=str(file_path),
            )
        ]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [
            ValidationIssue(
                rule="file.parse",
                message=f"Invalid JSON: {exc}",
                file_path=str(file_path),
            )
        ]

    if not isinstance(parsed, dict):
        return [], [
            ValidationIssue(
                rule="file.shape",
                message="Requirement file must contain one JSON object.",
                file_path=str(file_path),
            )
        ]

    return [parsed], issues


def validate_entries_against_schema(
    entries: list[dict[str, Any]],
    file_path: Path,
    schema: dict[str, Any],
) -> list[ValidationIssue]:
    """Validate a requirement entry list against JSON Schema."""

    validator = Draft202012Validator(schema)
    issues: list[ValidationIssue] = []

    for idx, entry in enumerate(entries):
        errors = sorted(validator.iter_errors(entry), key=lambda err: list(err.path))
        for err in errors:
            path = ".".join(str(part) for part in err.path)
            prefix = f"{path}: " if path else ""
            issues.append(
                ValidationIssue(
                    rule="schema",
                    message=f"{prefix}{err.message}",
                    file_path=str(file_path),
                    entry_index=idx,
                    ruid=(
                        entry.get("ruid")
                        if isinstance(entry.get("ruid"), str)
                        else None
                    ),
                )
            )

    return issues


def validate_requirement_file(
    file_path: Path,
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    """Run parser + schema validation for one JSON requirement file."""

    entries, issues = load_requirement_file(file_path)
    if issues:
        return entries, issues

    schema_issues = validate_entries_against_schema(entries, file_path, schema)
    return entries, schema_issues
