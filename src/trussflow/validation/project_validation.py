"""Project-wide semantic validation for Trussflow requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trussflow.validation.schema_validation import (
    ValidationIssue,
    load_amendment_schema,
    load_errata_schema,
    load_schema,
    validate_amendment_file,
    validate_errata_file,
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


def _collect_artifact_records(
    artifact_dir: Path,
    glob_pattern: str,
    schema: dict[str, Any],
    validate_file: Any,
) -> tuple[list[ValidationIssue], list[dict[str, Any]]]:
    issues: list[ValidationIssue] = []
    entries: list[dict[str, Any]] = []

    if not artifact_dir.exists():
        return [
            ValidationIssue(
                rule="path.missing",
                message=f"Path does not exist: {artifact_dir}",
                file_path=str(artifact_dir),
            )
        ], entries

    if not artifact_dir.is_dir():
        return [
            ValidationIssue(
                rule="path.type",
                message=f"Path must be a directory: {artifact_dir}",
                file_path=str(artifact_dir),
            )
        ], entries

    file_paths = sorted(artifact_dir.rglob(glob_pattern))
    if not file_paths:
        return [
            ValidationIssue(
                rule="artifact.empty",
                message=f"No JSON files were found under: {artifact_dir}",
                file_path=str(artifact_dir),
            )
        ], entries

    for file_path in file_paths:
        file_entries, file_issues = validate_file(file_path, schema)
        issues.extend(file_issues)
        if file_issues:
            continue
        for idx, entry in enumerate(file_entries):
            copied = dict(entry)
            copied["_file_path"] = str(file_path)
            copied["_entry_index"] = idx
            entries.append(copied)

    return issues, entries


def _validate_errata_semantics(
    errata_entries: list[dict[str, Any]],
    requirements_by_ruid: dict[str, RequirementRecord],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    seen_errata: set[str] = set()
    for entry in errata_entries:
        errata_id = entry.get("errata_id")
        file_path = str(entry.get("_file_path", ""))
        entry_index = entry.get("_entry_index")
        if isinstance(errata_id, str):
            if errata_id in seen_errata:
                issues.append(
                    ValidationIssue(
                        rule="errata.id.unique",
                        message=f"Errata id '{errata_id}' is duplicated.",
                        file_path=file_path,
                        entry_index=entry_index,
                    )
                )
            seen_errata.add(errata_id)

        affected_ruids = entry.get("affected_ruids", [])
        for ref in affected_ruids:
            if ref not in requirements_by_ruid:
                issues.append(
                    ValidationIssue(
                        rule="errata.target.exists",
                        message=f"Errata target RUID '{ref}' does not exist in requirements baseline.",
                        file_path=file_path,
                        entry_index=entry_index,
                    )
                )

        solutions = entry.get("solutions", [])
        seen_solution_ids: set[str] = set()
        for solution in solutions:
            solution_id = solution.get("solution_id")
            if not isinstance(solution_id, str):
                continue
            if solution_id in seen_solution_ids:
                issues.append(
                    ValidationIssue(
                        rule="errata.solution_id.unique",
                        message=f"Errata '{errata_id}' has duplicate solution_id '{solution_id}'.",
                        file_path=file_path,
                        entry_index=entry_index,
                    )
                )
            seen_solution_ids.add(solution_id)

    return issues


def _validate_amendment_semantics(
    amendment_entries: list[dict[str, Any]],
    requirements_by_ruid: dict[str, RequirementRecord],
    errata_entries: list[dict[str, Any]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    by_rn = {record.parsed_ruid.rn: record for record in requirements_by_ruid.values()}

    def _has_immediate_child(rn: str) -> bool:
        return any(
            other.parsed_ruid.rn.startswith(rn)
            and len(other.parsed_ruid.rn) == len(rn) + 1
            for other in requirements_by_ruid.values()
        )

    errata_by_id: dict[str, dict[str, Any]] = {
        str(entry["errata_id"]): entry
        for entry in errata_entries
        if isinstance(entry.get("errata_id"), str)
    }

    seen_amendment: set[str] = set()
    seen_new_ruids: set[str] = set(requirements_by_ruid)
    for entry in amendment_entries:
        amendment_id = entry.get("amendment_id")
        file_path = str(entry.get("_file_path", ""))
        entry_index = entry.get("_entry_index")
        approval_timestamp = _parse_timestamp(entry.get("approval_timestamp"))
        if approval_timestamp is None:
            issues.append(
                ValidationIssue(
                    rule="amendment.approval_timestamp.parse",
                    message=(
                        "Amendment approval_timestamp must be a valid UTC instant in "
                        "YYYY-MM-DDTHH:MM:SSZ format."
                    ),
                    file_path=file_path,
                    entry_index=entry_index,
                )
            )

        if isinstance(amendment_id, str):
            if amendment_id in seen_amendment:
                issues.append(
                    ValidationIssue(
                        rule="amendment.id.unique",
                        message=f"Amendment id '{amendment_id}' is duplicated.",
                        file_path=file_path,
                        entry_index=entry_index,
                    )
                )
            seen_amendment.add(amendment_id)

        errata_id = entry.get("errata_id")
        linked_errata = errata_by_id.get(str(errata_id))
        if linked_errata is None:
            issues.append(
                ValidationIssue(
                    rule="amendment.errata.exists",
                    message=f"Amendment references unknown errata_id '{errata_id}'.",
                    file_path=file_path,
                    entry_index=entry_index,
                )
            )
            continue

        selected_solution_id = entry.get("selected_solution_id")
        solution_ids = {
            str(solution.get("solution_id"))
            for solution in linked_errata.get("solutions", [])
            if isinstance(solution, dict) and solution.get("solution_id")
        }
        if str(selected_solution_id) not in solution_ids:
            issues.append(
                ValidationIssue(
                    rule="amendment.solution.exists",
                    message=(
                        f"Amendment selected_solution_id '{selected_solution_id}' does not exist "
                        f"in errata '{errata_id}'."
                    ),
                    file_path=file_path,
                    entry_index=entry_index,
                )
            )

        for change in entry.get("changes", []):
            if not isinstance(change, dict):
                continue
            action = change.get("action")
            target_ruid = change.get("target_ruid")
            parent_ruid = change.get("parent_ruid")
            new_state = (
                change.get("new_state")
                if isinstance(change.get("new_state"), dict)
                else {}
            )
            new_ruid = change.get("new_ruid")
            new_timestamp_raw = change.get("new_timestamp")
            new_timestamp = _parse_timestamp(new_timestamp_raw)
            new_parsed = (
                ParsedRuid.from_string(new_ruid) if isinstance(new_ruid, str) else None
            )

            if action in {"create", "supersede"}:
                if not isinstance(new_ruid, str) or new_parsed is None:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.new_ruid.parse",
                            message="Change requires a valid new_ruid.",
                            file_path=file_path,
                            entry_index=entry_index,
                        )
                    )
                elif new_ruid in seen_new_ruids:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.new_ruid.unique",
                            message=f"Change new_ruid '{new_ruid}' already exists or is duplicated.",
                            file_path=file_path,
                            entry_index=entry_index,
                            ruid=new_ruid,
                        )
                    )
                else:
                    seen_new_ruids.add(new_ruid)

                if new_timestamp is None:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.new_timestamp.parse",
                            message=(
                                "Change new_timestamp must be a valid UTC instant in "
                                "YYYY-MM-DDTHH:MM:SSZ format."
                            ),
                            file_path=file_path,
                            entry_index=entry_index,
                        )
                    )
                elif approval_timestamp is not None and not (
                    new_timestamp > approval_timestamp
                ):
                    issues.append(
                        ValidationIssue(
                            rule="amendment.new_timestamp.order",
                            message="Change new_timestamp must be later than amendment approval_timestamp.",
                            file_path=file_path,
                            entry_index=entry_index,
                        )
                    )

            target: RequirementRecord | None = None
            if action != "create":
                if not isinstance(target_ruid, str):
                    continue
                if target_ruid not in requirements_by_ruid:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.target.exists",
                            message=f"Change target_ruid '{target_ruid}' does not exist in requirements baseline.",
                            file_path=file_path,
                            entry_index=entry_index,
                        )
                    )
                    continue
                target = requirements_by_ruid[target_ruid]

            if (
                target is not None
                and action
                in {
                    "state_transition",
                    "scope_change",
                    "ref_update",
                    "move_hierarchy",
                }
                and target.parsed_ruid.rs == "c"
            ):
                issues.append(
                    ValidationIssue(
                        rule="amendment.immutable_published",
                        message=(
                            f"Published requirement '{target_ruid}' cannot be modified in place; "
                            "use action='supersede'."
                        ),
                        file_path=file_path,
                        entry_index=entry_index,
                        ruid=target_ruid,
                    )
                )

            if action == "supersede" and target is not None:
                supersedes = change.get("supersedes", [])
                if target_ruid not in supersedes:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.supersedes.target",
                            message=(
                                f"Supersede change for '{target_ruid}' must include that RUID in supersedes[]."
                            ),
                            file_path=file_path,
                            entry_index=entry_index,
                            ruid=target_ruid,
                        )
                    )

                if (
                    isinstance(new_parsed, ParsedRuid)
                    and new_parsed.rn == target.parsed_ruid.rn
                ):
                    issues.append(
                        ValidationIssue(
                            rule="amendment.supersede.rn_new",
                            message=(
                                f"Supersede change for '{target_ruid}' must use a new RN in new_ruid."
                            ),
                            file_path=file_path,
                            entry_index=entry_index,
                            ruid=target_ruid,
                        )
                    )

                if isinstance(supersedes, list) and new_timestamp is not None:
                    for superseded_ruid in supersedes:
                        superseded_target = requirements_by_ruid.get(superseded_ruid)
                        if superseded_target is None:
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.supersedes.exists",
                                    message=(
                                        f"Supersede reference '{superseded_ruid}' does not exist in requirements baseline."
                                    ),
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=target_ruid,
                                )
                            )
                            continue
                        if not (new_timestamp > superseded_target.timestamp):
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.supersedes.older",
                                    message=(
                                        f"Supersede new_timestamp must be later than superseded requirement "
                                        f"'{superseded_ruid}' timestamp."
                                    ),
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=target_ruid,
                                )
                            )

            if action == "create":
                if (
                    isinstance(parent_ruid, str)
                    and parent_ruid not in requirements_by_ruid
                ):
                    issues.append(
                        ValidationIssue(
                            rule="amendment.parent.exists",
                            message=f"Create change parent_ruid '{parent_ruid}' does not exist.",
                            file_path=file_path,
                            entry_index=entry_index,
                        )
                    )

                if isinstance(parent_ruid, str) and parent_ruid in requirements_by_ruid:
                    parent = requirements_by_ruid[parent_ruid]
                    if parent.parsed_ruid.rs == "t":
                        issues.append(
                            ValidationIssue(
                                rule="amendment.create.parent_leaf",
                                message=(
                                    f"Create change cannot add a child under leaf requirement '{parent_ruid}' (RS='t')."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=parent_ruid,
                            )
                        )

                    if isinstance(new_parsed, ParsedRuid):
                        if not (
                            new_parsed.rn.startswith(parent.parsed_ruid.rn)
                            and len(new_parsed.rn) == len(parent.parsed_ruid.rn) + 1
                        ):
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.create.hierarchy",
                                    message=(
                                        f"Create change new_ruid '{new_parsed.raw}' must be a direct child of "
                                        f"parent '{parent_ruid}'."
                                    ),
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=new_parsed.raw,
                                )
                            )

                        if new_parsed.rl < parent.parsed_ruid.rl:
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.create.rl_monotonic",
                                    message=(
                                        f"Create change child RL must be >= parent RL. Parent {parent_ruid} has RL "
                                        f"{parent.parsed_ruid.rl}, child {new_parsed.raw} has RL {new_parsed.rl}."
                                    ),
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=new_parsed.raw,
                                )
                            )

                        if parent.parsed_ruid.rs == "p" and new_parsed.rs != "p":
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.create.rs_propagation",
                                    message=(
                                        f"Create change child '{new_parsed.raw}' must keep state 'p' because "
                                        f"parent '{parent_ruid}' is proposed."
                                    ),
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=new_parsed.raw,
                                )
                            )

            if action == "state_transition" and target is not None:
                new_rs = new_state.get("rs")
                if isinstance(new_rs, str):
                    old_rs = target.parsed_ruid.rs
                    if old_rs == "c" and new_rs != "c":
                        issues.append(
                            ValidationIssue(
                                rule="amendment.state_transition.demotion",
                                message=(
                                    f"State transition cannot demote published requirement '{target_ruid}' from 'c'."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=target_ruid,
                            )
                        )
                    if old_rs == "t" and new_rs != "t":
                        issues.append(
                            ValidationIssue(
                                rule="amendment.state_transition.t_locked",
                                message=(
                                    f"State transition cannot change requirement '{target_ruid}' from 't'."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=target_ruid,
                            )
                        )

                    parent = by_rn.get(target.parsed_ruid.rn[:-1])
                    if parent and parent.parsed_ruid.rs == "p" and new_rs != "p":
                        issues.append(
                            ValidationIssue(
                                rule="amendment.state_transition.rs_propagation",
                                message=(
                                    f"State transition for '{target_ruid}' must keep state 'p' because parent "
                                    f"'{parent.parsed_ruid.raw}' is proposed."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=target_ruid,
                            )
                        )

                    if new_rs == "t" and _has_immediate_child(target.parsed_ruid.rn):
                        issues.append(
                            ValidationIssue(
                                rule="amendment.state_transition.leaf",
                                message=(
                                    f"State transition cannot set '{target_ruid}' to 't' because it has children."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=target_ruid,
                            )
                        )

            if (
                action == "move_hierarchy"
                and isinstance(parent_ruid, str)
                and target is not None
            ):
                new_parent = requirements_by_ruid.get(parent_ruid)
                if new_parent is None:
                    issues.append(
                        ValidationIssue(
                            rule="amendment.parent.exists",
                            message=f"Move change parent_ruid '{parent_ruid}' does not exist.",
                            file_path=file_path,
                            entry_index=entry_index,
                            ruid=target_ruid,
                        )
                    )
                else:
                    target_parent_rn = target.parsed_ruid.rn[:-1]
                    if new_parent.parsed_ruid.rn != target_parent_rn:
                        issues.append(
                            ValidationIssue(
                                rule="amendment.move_hierarchy.parent_prefix",
                                message=(
                                    f"Move change parent '{parent_ruid}' is incompatible with immutable RN of "
                                    f"'{target_ruid}'."
                                ),
                                file_path=file_path,
                                entry_index=entry_index,
                                ruid=target_ruid,
                            )
                        )

            if action == "ref_update" and target is not None:
                refs = (
                    new_state.get("refs")
                    if isinstance(new_state.get("refs"), dict)
                    else {}
                )
                for key in REF_KEYS:
                    for ref in refs.get(key, []):
                        if (
                            ref not in seen_new_ruids
                            and ref not in requirements_by_ruid
                        ):
                            issues.append(
                                ValidationIssue(
                                    rule="amendment.refs.exists",
                                    message=f"Reference '{ref}' in refs.{key} does not exist in baseline or proposed changes.",
                                    file_path=file_path,
                                    entry_index=entry_index,
                                    ruid=target_ruid,
                                )
                            )

    return issues


def validate_change_artifacts(
    requirements_dir: Path,
    errata_dir: Path,
    amendments_dir: Path,
    requirement_schema_path: Path | None = None,
    errata_schema_path: Path | None = None,
    amendment_schema_path: Path | None = None,
) -> list[ValidationIssue]:
    """Validate requirements baseline plus errata/amendment schema and semantic linkage rules."""

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

    requirement_schema = load_schema(requirement_schema_path)
    requirements_records, issues = _collect_records(
        requirements_dir, requirement_schema
    )
    requirements_by_ruid = {
        record.parsed_ruid.raw: record for record in requirements_records
    }

    errata_schema = load_errata_schema(errata_schema_path)
    errata_issues, errata_entries = _collect_artifact_records(
        errata_dir,
        "*.json",
        errata_schema,
        validate_errata_file,
    )
    issues.extend(errata_issues)

    amendment_schema = load_amendment_schema(amendment_schema_path)
    amendment_issues, amendment_entries = _collect_artifact_records(
        amendments_dir,
        "*.json",
        amendment_schema,
        validate_amendment_file,
    )
    issues.extend(amendment_issues)

    issues.extend(_validate_errata_semantics(errata_entries, requirements_by_ruid))
    issues.extend(
        _validate_amendment_semantics(
            amendment_entries,
            requirements_by_ruid,
            errata_entries,
        )
    )

    return issues
