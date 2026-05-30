"""Project-wide semantic validation for Trussflow requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from trussflow.validation.schema_validation import (
    ValidationIssue,
    load_schema,
    validate_requirement_file,
)

RUID_RE = re.compile(r"^([0-9A-Z]+)([0-3])([cpt])$")
REQUIREMENT_MAY_RE = re.compile(r"\bmay\b", re.IGNORECASE)
REF_KEYS = ("depends_on", "related_to", "supersedes")


@dataclass(slots=True)
class ParsedRuid:
    """RUID decomposition helper."""

    raw: str
    rn: str
    rl: int
    rs: str

    @classmethod
    def from_string(cls, value: str) -> "ParsedRuid | None":
        match = RUID_RE.match(value)
        if not match:
            return None
        rn, rl, rs = match.groups()
        return cls(raw=value, rn=rn, rl=int(rl), rs=rs)


@dataclass(slots=True)
class RequirementRecord:
    """Normalized requirement entry for semantic validation."""

    parsed_ruid: ParsedRuid
    timestamp: datetime
    text: str
    refs: dict[str, list[str]]
    file_path: Path
    entry_index: int


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def _collect_records(
    requirements_dir: Path,
    schema: dict,
) -> tuple[list[RequirementRecord], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    records: list[RequirementRecord] = []

    for file_path in sorted(requirements_dir.rglob("*.json")):
        entries, file_issues = validate_requirement_file(file_path, schema)
        issues.extend(file_issues)
        if file_issues:
            continue

        for idx, entry in enumerate(entries):
            ruid_value = entry["ruid"]
            parsed = ParsedRuid.from_string(ruid_value)
            if parsed is None:
                issues.append(
                    ValidationIssue(
                        rule="ruid.parse",
                        message=f"Unable to parse RUID '{ruid_value}'.",
                        file_path=str(file_path),
                        entry_index=idx,
                    )
                )
                continue

            timestamp = _parse_timestamp(entry["timestamp"])
            if timestamp is None:
                issues.append(
                    ValidationIssue(
                        rule="timestamp.parse",
                        message="Timestamp must be a valid UTC instant in YYYY-MM-DDTHH:MM:SSZ format.",
                        file_path=str(file_path),
                        entry_index=idx,
                        ruid=ruid_value,
                    )
                )
                continue

            refs = entry.get("refs", {})
            normalized_refs = {key: list(refs.get(key, [])) for key in REF_KEYS}

            records.append(
                RequirementRecord(
                    parsed_ruid=parsed,
                    timestamp=timestamp,
                    text=entry["text"],
                    refs=normalized_refs,
                    file_path=file_path,
                    entry_index=idx,
                )
            )

    return records, issues


def _validate_rn_uniqueness(records: list[RequirementRecord]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: dict[str, RequirementRecord] = {}

    for record in records:
        rn = record.parsed_ruid.rn
        if rn in seen:
            original = seen[rn]
            issues.append(
                ValidationIssue(
                    rule="rn.unique",
                    message=(
                        f"RN '{rn}' is duplicated by {record.parsed_ruid.raw} and "
                        f"{original.parsed_ruid.raw}."
                    ),
                    file_path=str(record.file_path),
                    entry_index=record.entry_index,
                    ruid=record.parsed_ruid.raw,
                )
            )
            continue
        seen[rn] = record

    return issues


def _validate_hierarchy_and_state(
    records: list[RequirementRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_rn = {record.parsed_ruid.rn: record for record in records}

    for record in records:
        parsed = record.parsed_ruid
        parent_rn = parsed.rn[:-1]
        if parent_rn and parent_rn in by_rn:
            parent = by_rn[parent_rn].parsed_ruid
            if parsed.rl < parent.rl:
                issues.append(
                    ValidationIssue(
                        rule="rl.monotonic",
                        message=(
                            f"Child RL must be >= parent RL. Parent {parent.raw} has RL {parent.rl}, "
                            f"child {parsed.raw} has RL {parsed.rl}."
                        ),
                        file_path=str(record.file_path),
                        entry_index=record.entry_index,
                        ruid=parsed.raw,
                    )
                )
            if parent.rs == "p" and parsed.rs != "p":
                issues.append(
                    ValidationIssue(
                        rule="rs.propagation",
                        message=(
                            f"Descendant {parsed.raw} must keep state 'p' because parent {parent.raw} is proposed."
                        ),
                        file_path=str(record.file_path),
                        entry_index=record.entry_index,
                        ruid=parsed.raw,
                    )
                )

        if parsed.rl == 3:
            has_eligible_ancestor = False
            for length in range(len(parsed.rn) - 1, 0, -1):
                ancestor = by_rn.get(parsed.rn[:length])
                if ancestor and ancestor.parsed_ruid.rl in (0, 1, 2):
                    has_eligible_ancestor = True
                    break
            if not has_eligible_ancestor:
                issues.append(
                    ValidationIssue(
                        rule="rl.ancestor",
                        message=(
                            f"Requirement {parsed.raw} with RL=3 must have an ancestor with RL in [0,1,2]."
                        ),
                        file_path=str(record.file_path),
                        entry_index=record.entry_index,
                        ruid=parsed.raw,
                    )
                )

        if parsed.rs == "t":
            has_child = any(
                other.parsed_ruid.rn.startswith(parsed.rn)
                and len(other.parsed_ruid.rn) == len(parsed.rn) + 1
                for other in records
            )
            if has_child:
                issues.append(
                    ValidationIssue(
                        rule="rs.leaf",
                        message=f"Requirement {parsed.raw} with RS='t' must be a leaf.",
                        file_path=str(record.file_path),
                        entry_index=record.entry_index,
                        ruid=parsed.raw,
                    )
                )

    return issues


def _validate_cross_references(
    records: list[RequirementRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_ruid = {record.parsed_ruid.raw: record for record in records}

    for record in records:
        current_ruid = record.parsed_ruid.raw
        for key in REF_KEYS:
            for ref in record.refs.get(key, []):
                target = by_ruid.get(ref)
                if target is None:
                    issues.append(
                        ValidationIssue(
                            rule="refs.exists",
                            message=f"Reference '{ref}' in refs.{key} does not exist.",
                            file_path=str(record.file_path),
                            entry_index=record.entry_index,
                            ruid=current_ruid,
                        )
                    )
                    continue

                if key == "supersedes" and not (record.timestamp > target.timestamp):
                    issues.append(
                        ValidationIssue(
                            rule="refs.supersedes.older",
                            message=(
                                f"Requirement {current_ruid} must be newer than superseded requirement {ref}."
                            ),
                            file_path=str(record.file_path),
                            entry_index=record.entry_index,
                            ruid=current_ruid,
                        )
                    )

    return issues


def _validate_requirement_language(
    records: list[RequirementRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for record in records:
        if REQUIREMENT_MAY_RE.search(record.text):
            issues.append(
                ValidationIssue(
                    rule="text.normative_may",
                    message=(
                        f"Requirement {record.parsed_ruid.raw} uses 'may' in requirement text; "
                        "use 'shall' for requirements per NASA guidance."
                    ),
                    file_path=str(record.file_path),
                    entry_index=record.entry_index,
                    ruid=record.parsed_ruid.raw,
                )
            )

    return issues


def _validate_storage_model(
    requirements_dir: Path, records: list[RequirementRecord]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for folder in sorted(path for path in requirements_dir.rglob("*") if path.is_dir()):
        if not any(folder.iterdir()):
            issues.append(
                ValidationIssue(
                    rule="storage.non_empty_folder",
                    message="Empty folders are forbidden under requirements/.",
                    file_path=str(folder),
                )
            )

    by_rn = {record.parsed_ruid.rn: record for record in records}
    for folder in sorted(path for path in requirements_dir.rglob("*") if path.is_dir()):
        if folder == requirements_dir:
            continue
        folder_rn = folder.name
        owner = by_rn.get(folder_rn)
        if owner is None:
            issues.append(
                ValidationIssue(
                    rule="storage.folder_owner",
                    message=f"Folder '{folder}' does not match any existing requirement RN.",
                    file_path=str(folder),
                )
            )
            continue

        owner_has_children = any(
            other.parsed_ruid.rn.startswith(folder_rn)
            and len(other.parsed_ruid.rn) == len(folder_rn) + 1
            for other in records
        )
        if not owner_has_children:
            issues.append(
                ValidationIssue(
                    rule="storage.folder_children",
                    message=(
                        f"Folder '{folder}' exists but requirement {owner.parsed_ruid.raw} has no children."
                    ),
                    file_path=str(folder),
                    ruid=owner.parsed_ruid.raw,
                )
            )

    return issues


def validate_requirements_tree(
    requirements_dir: Path,
    schema_path: Path | None = None,
) -> list[ValidationIssue]:
    """Validate schema + hierarchy/state/reference/storage rules for requirements tree."""

    if not requirements_dir.exists():
        return [
            ValidationIssue(
                rule="path.missing",
                message=f"Requirements path does not exist: {requirements_dir}",
                file_path=str(requirements_dir),
            )
        ]

    if not requirements_dir.is_dir():
        return [
            ValidationIssue(
                rule="path.type",
                message=f"Requirements path must be a directory: {requirements_dir}",
                file_path=str(requirements_dir),
            )
        ]

    schema = load_schema(schema_path)
    records, issues = _collect_records(requirements_dir, schema)

    if not records and not issues:
        return [
            ValidationIssue(
                rule="requirements.empty",
                message="No requirement JSON files were found.",
                file_path=str(requirements_dir),
            )
        ]

    issues.extend(_validate_rn_uniqueness(records))
    issues.extend(_validate_hierarchy_and_state(records))
    issues.extend(_validate_cross_references(records))
    issues.extend(_validate_requirement_language(records))
    issues.extend(_validate_storage_model(requirements_dir, records))
    return issues
