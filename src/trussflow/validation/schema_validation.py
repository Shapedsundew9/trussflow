"""Schema-based validation for Trussflow requirement files."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class _NoDatesSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that keeps timestamp-like scalars as strings."""


_NoDatesSafeLoader.yaml_implicit_resolvers = deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)

for first_char, resolvers in list(_NoDatesSafeLoader.yaml_implicit_resolvers.items()):
    _NoDatesSafeLoader.yaml_implicit_resolvers[first_char] = [
        pair for pair in resolvers if pair[0] != "tag:yaml.org,2002:timestamp"
    ]


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
    """Load a YAML requirement list and return entries plus parse issues."""

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
                message="Requirement YAML must be ASCII.",
                file_path=str(file_path),
            )
        ]

    try:
        parsed = yaml.load(text, Loader=_NoDatesSafeLoader)
    except yaml.YAMLError as exc:
        return [], [
            ValidationIssue(
                rule="file.yaml",
                message=f"Invalid YAML: {exc}",
                file_path=str(file_path),
            )
        ]

    if parsed is None:
        return [], []

    if not isinstance(parsed, list):
        return [], [
            ValidationIssue(
                rule="file.shape",
                message="Requirement file must contain a YAML list of requirement entries.",
                file_path=str(file_path),
            )
        ]

    entries: list[dict[str, Any]] = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            issues.append(
                ValidationIssue(
                    rule="entry.shape",
                    message="Each requirement entry must be a YAML object.",
                    file_path=str(file_path),
                    entry_index=idx,
                )
            )
            continue
        entries.append(item)

    return entries, issues


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


def _scalar_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    return type(value).__name__


def detect_yaml_scalar_coercions(
    entries: list[dict[str, Any]],
    file_path: Path,
) -> list[ValidationIssue]:
    """Detect YAML implicit scalar typing where schema expects strings."""

    issues: list[ValidationIssue] = []
    scalar_types = (bool, int, float, type(None), date, datetime)
    top_level_string_fields = ("ruid", "timestamp", "text", "rationale", "scope")

    for idx, entry in enumerate(entries):
        ruid = entry.get("ruid") if isinstance(entry.get("ruid"), str) else None

        for key in top_level_string_fields:
            if key not in entry:
                continue
            value = entry[key]
            if isinstance(value, scalar_types) and not isinstance(value, str):
                issues.append(
                    ValidationIssue(
                        rule="yaml.scalar_coercion",
                        message=(
                            f"Field '{key}' was parsed as {_scalar_type_name(value)}; "
                            "quote the value if a string was intended."
                        ),
                        file_path=str(file_path),
                        entry_index=idx,
                        ruid=ruid,
                    )
                )

        refs = entry.get("refs")
        if not isinstance(refs, dict):
            continue

        for ref_key in ("depends_on", "related_to", "supersedes"):
            ref_values = refs.get(ref_key)
            if not isinstance(ref_values, list):
                continue
            for ref_idx, ref_value in enumerate(ref_values):
                if isinstance(ref_value, scalar_types) and not isinstance(
                    ref_value, str
                ):
                    issues.append(
                        ValidationIssue(
                            rule="yaml.scalar_coercion",
                            message=(
                                f"Field 'refs.{ref_key}[{ref_idx}]' was parsed as "
                                f"{_scalar_type_name(ref_value)}; quote the value if a string was intended."
                            ),
                            file_path=str(file_path),
                            entry_index=idx,
                            ruid=ruid,
                        )
                    )

    return issues


def validate_requirement_file(
    file_path: Path,
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[ValidationIssue]]:
    """Run parser + schema validation for one YAML file."""

    entries, issues = load_requirement_file(file_path)
    if issues:
        return entries, issues

    coercion_issues = detect_yaml_scalar_coercions(entries, file_path)
    if coercion_issues:
        return entries, coercion_issues

    schema_issues = validate_entries_against_schema(entries, file_path, schema)
    return entries, schema_issues
