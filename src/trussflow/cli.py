"""Command-line interface for Trussflow."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trussflow.validation import validate_change_artifacts, validate_requirements_tree
from trussflow.validation.schema_validation import (
    ValidationIssue,
    load_schema,
    validate_requirement_file,
)

RUID_RE = re.compile(r"^([0-9A-Z]+)([0-3])([cpt])$")
RN_RE = re.compile(r"^[0-9A-Z]+$")
RN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
REF_KEYS = ("depends_on", "related_to", "supersedes")
LIST_INCLUDE_FIELDS = (
    "ruid",
    "rn",
    "rl",
    "rs",
    "scope",
    "path",
    "text",
)


@dataclass(slots=True)
class RequirementDoc:
    """Loaded requirement entry and parsed metadata."""

    data: dict[str, Any]
    file_path: Path
    rn: str
    rl: int
    rs: str


def _parse_ruid(ruid: str) -> tuple[str, int, str] | None:
    match = RUID_RE.match(ruid)
    if not match:
        return None
    rn, rl, rs = match.groups()
    return rn, int(rl), rs


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def _issue(rule: str, message: str, file_path: str = "") -> ValidationIssue:
    return ValidationIssue(rule=rule, message=message, file_path=file_path)


def _load_requirements(
    requirements_dir: Path,
) -> tuple[list[RequirementDoc], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    docs: list[RequirementDoc] = []

    if not requirements_dir.exists():
        return [], [
            _issue(
                "path.missing",
                f"Requirements path does not exist: {requirements_dir}",
                str(requirements_dir),
            )
        ]

    if not requirements_dir.is_dir():
        return [], [
            _issue(
                "path.type",
                f"Requirements path must be a directory: {requirements_dir}",
                str(requirements_dir),
            )
        ]

    schema = load_schema()
    for file_path in sorted(requirements_dir.rglob("*.json")):
        entries, entry_issues = validate_requirement_file(file_path, schema)
        if entry_issues:
            issues.extend(entry_issues)
            continue
        if not entries:
            continue
        entry = entries[0]
        ruid = entry.get("ruid")
        if not isinstance(ruid, str):
            issues.append(
                _issue(
                    "ruid.parse",
                    "Requirement is missing a string ruid.",
                    str(file_path),
                )
            )
            continue
        parsed = _parse_ruid(ruid)
        if parsed is None:
            issues.append(
                _issue("ruid.parse", f"Unable to parse RUID '{ruid}'.", str(file_path))
            )
            continue
        rn, rl, rs = parsed
        docs.append(
            RequirementDoc(data=entry, file_path=file_path, rn=rn, rl=rl, rs=rs)
        )

    if not docs and not issues:
        issues.append(
            _issue(
                "requirements.empty",
                "No requirement JSON files were found.",
                str(requirements_dir),
            )
        )

    return docs, issues


def _build_indexes(
    docs: list[RequirementDoc],
) -> tuple[
    dict[str, RequirementDoc],
    dict[str, RequirementDoc],
    dict[str, list[RequirementDoc]],
]:
    by_ruid: dict[str, RequirementDoc] = {}
    by_rn: dict[str, RequirementDoc] = {}
    children_by_rn: dict[str, list[RequirementDoc]] = {}

    for doc in docs:
        ruid = str(doc.data["ruid"])
        by_ruid[ruid] = doc
        by_rn[doc.rn] = doc

    for doc in docs:
        parent_rn = doc.rn[:-1]
        children_by_rn.setdefault(parent_rn, []).append(doc)

    return by_ruid, by_rn, children_by_rn


def _output(
    *,
    as_json: bool,
    ok: bool,
    command: str,
    result: dict[str, Any] | None = None,
    warnings: list[ValidationIssue] | None = None,
    errors: list[ValidationIssue] | None = None,
) -> int:
    warn_items = warnings or []
    err_items = errors or []
    if as_json:
        payload = {
            "ok": ok,
            "command": command,
            "result": result or {},
            "warnings": [issue.to_dict() for issue in warn_items],
            "errors": [issue.to_dict() for issue in err_items],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if ok else 1

    status = "OK" if ok else "FAILED"
    print(f"{command}: {status}")
    if result:
        for key, value in result.items():
            print(f"- {key}: {value}")
    for issue in warn_items:
        print(f"- warning {issue.rule}: {issue.message}")
    for issue in err_items:
        print(f"- error {issue.rule}: {issue.message}")
    return 0 if ok else 1


def _next_child_rn(parent_rn: str, used_rns: set[str]) -> str | None:
    for ch in RN_CHARS:
        candidate = f"{parent_rn}{ch}"
        if candidate not in used_rns:
            return candidate
    return None


def _rn_exhausted_issue(*, parent_rn: str, parent_ruid: str) -> ValidationIssue:
    return _issue(
        "rn.exhausted",
        (
            f"No available one-character RN extension under parent RN '{parent_rn}' "
            f"(parent {parent_ruid}). Maximum immediate children is {len(RN_CHARS)}. "
            "Direction: add hierarchy depth by creating a child under an existing sibling "
            "instead of adding another direct sibling at this level."
        ),
    )


def _resolve_rn_selector(
    selector: str,
    *,
    by_rn: dict[str, RequirementDoc] | None = None,
) -> str | None:
    _ = by_rn
    parsed = _parse_ruid(selector)
    if parsed is not None:
        rn, _, _ = parsed
        return rn

    if RN_RE.match(selector):
        return selector
    return None


def _resolve_requirement(
    selector: str,
    *,
    by_rn: dict[str, RequirementDoc],
) -> tuple[RequirementDoc | None, ValidationIssue | None]:
    rn = _resolve_rn_selector(selector, by_rn=by_rn)
    if rn is None:
        return None, _issue(
            "ruid.parse",
            f"Identifier must be RN or full RUID: '{selector}'.",
        )

    target = by_rn.get(rn)
    if target is None:
        return None, _issue(
            "requirement.not_found",
            f"Requirement not found for RN '{rn}'.",
        )
    return target, None


def _make_requirement_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "timestamp": _utc_now_iso(),
        "text": args.text,
        "rationale": args.rationale,
        "scope": args.scope,
        "refs": {
            "depends_on": list(args.depends_on or []),
            "related_to": list(args.related_to or []),
            "supersedes": list(args.supersedes or []),
        },
    }


def _validate_refs_exist(
    refs: dict[str, list[str]], by_ruid: dict[str, RequirementDoc]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in REF_KEYS:
        for ref in refs.get(key, []):
            if ref not in by_ruid:
                issues.append(
                    _issue(
                        "refs.exists",
                        f"Reference '{ref}' in refs.{key} does not exist.",
                    )
                )
    return issues


def _validate_proposed_requirement(
    *,
    parent: RequirementDoc,
    child_rl: int,
    child_rs: str,
    child_refs: dict[str, list[str]],
    child_timestamp: str,
    by_ruid: dict[str, RequirementDoc],
    by_rn: dict[str, RequirementDoc],
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []

    if child_rl < parent.rl:
        errors.append(
            _issue(
                "rl.monotonic",
                (
                    f"Child RL must be >= parent RL. Parent {parent.data['ruid']} has RL {parent.rl}, "
                    f"child RL is {child_rl}."
                ),
            )
        )

    if parent.rs == "p" and child_rs != "p":
        errors.append(
            _issue(
                "rs.propagation",
                (
                    f"Descendant must keep state 'p' because parent {parent.data['ruid']} is proposed."
                ),
            )
        )

    if child_rl == 3:
        has_eligible_ancestor = parent.rl in (0, 1, 2)
        ancestor_rn = parent.rn[:-1]
        while not has_eligible_ancestor and ancestor_rn:
            ancestor = by_rn.get(ancestor_rn)
            if ancestor and ancestor.rl in (0, 1, 2):
                has_eligible_ancestor = True
                break
            ancestor_rn = ancestor_rn[:-1]

        if not has_eligible_ancestor:
            errors.append(
                _issue(
                    "rl.ancestor",
                    "A requirement with RL=3 must have an ancestor with RL in [0,1,2].",
                )
            )

    ref_issues = _validate_refs_exist(child_refs, by_ruid)
    errors.extend(ref_issues)

    child_ts = _parse_timestamp(child_timestamp)
    if child_ts is None:
        errors.append(
            _issue(
                "timestamp.parse",
                "Timestamp must be a valid UTC instant in YYYY-MM-DDTHH:MM:SSZ format.",
            )
        )
    else:
        for superseded_ruid in child_refs.get("supersedes", []):
            superseded = by_ruid.get(superseded_ruid)
            if superseded is None:
                continue
            superseded_ts = _parse_timestamp(superseded.data.get("timestamp"))
            if superseded_ts is None:
                continue
            if child_ts <= superseded_ts:
                errors.append(
                    _issue(
                        "refs.supersedes.older",
                        (
                            f"New requirement must be newer than superseded requirement {superseded_ruid}."
                        ),
                    )
                )

    return warnings, errors


def _write_requirement_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def _requirement_create_root(args: argparse.Namespace) -> int:
    requirements_dir = Path(args.requirements)

    if requirements_dir.exists() and not requirements_dir.is_dir():
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement create-root",
            errors=[
                _issue(
                    "path.type",
                    f"Requirements path must be a directory: {requirements_dir}",
                )
            ],
        )

    if requirements_dir.exists():
        existing_json = sorted(requirements_dir.rglob("*.json"))
        if existing_json:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement create-root",
                errors=[
                    _issue(
                        "requirement.root.exists",
                        "Cannot create root requirement because requirement files already exist.",
                    )
                ],
            )

    if not RN_RE.match(args.rn):
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement create-root",
            errors=[
                _issue(
                    "rn.parse",
                    f"RN must match pattern [0-9A-Z]+: '{args.rn}'.",
                )
            ],
        )

    payload = _make_requirement_payload(args)
    payload["ruid"] = f"{args.rn}{args.rl}{args.rs}"

    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []

    ref_issues = _validate_refs_exist(payload["refs"], by_ruid={})
    errors.extend(ref_issues)

    if re.search(r"\bmay\b", str(payload.get("text", "")), re.IGNORECASE):
        warnings.append(
            _issue(
                "text.normative_may",
                "Requirement text uses 'may'; use 'shall' for normative requirements.",
            )
        )

    if errors:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement create-root",
            warnings=warnings,
            errors=errors,
        )

    target_path = requirements_dir / "root.json"
    result = {
        "mode": "create-root",
        "dry_run": not args.apply,
        "ruid": payload["ruid"],
        "path": str(target_path),
        "requirement": payload,
    }

    if not args.apply:
        return _output(
            as_json=args.as_json,
            ok=True,
            command="requirement create-root",
            warnings=warnings,
            result=result,
        )

    _write_requirement_file(target_path, payload)
    return _output(
        as_json=args.as_json,
        ok=True,
        command="requirement create-root",
        warnings=warnings,
        result=result,
    )


def _requirement_get(args: argparse.Namespace) -> int:
    docs, issues = _load_requirements(Path(args.requirements))
    if issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement get",
            errors=issues,
        )

    _, by_rn, _ = _build_indexes(docs)
    target, resolve_issue = _resolve_requirement(args.ruid, by_rn=by_rn)
    if resolve_issue is not None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement get",
            errors=[resolve_issue],
        )

    return _output(
        as_json=args.as_json,
        ok=True,
        command="requirement get",
        result={
            "selector": args.ruid,
            "rn": target.rn,
            "ruid": target.data["ruid"],
            "path": str(target.file_path),
            "requirement": target.data,
        },
    )


def _requirement_list(args: argparse.Namespace) -> int:
    docs, issues = _load_requirements(Path(args.requirements))
    if issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement list",
            errors=issues,
        )

    _, by_rn, _ = _build_indexes(docs)
    items = docs
    if args.parent:
        parent_rn = _resolve_rn_selector(args.parent, by_rn=by_rn)
        if parent_rn is None:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement list",
                errors=[
                    _issue(
                        "ruid.parse",
                        f"Parent selector must be RN or full RUID: '{args.parent}'.",
                    )
                ],
            )
        items = [
            doc for doc in items if doc.rn.startswith(parent_rn) and doc.rn != parent_rn
        ]
    if args.rl is not None:
        items = [doc for doc in items if doc.rl == args.rl]
    if args.rs is not None:
        items = [doc for doc in items if doc.rs == args.rs]
    if args.scope is not None:
        items = [doc for doc in items if doc.data.get("scope") == args.scope]
    if args.text_contains:
        needle = args.text_contains.lower()
        items = [
            doc for doc in items if needle in str(doc.data.get("text", "")).lower()
        ]

    items = sorted(items, key=lambda doc: str(doc.data["ruid"]))
    if args.limit is not None:
        items = items[: args.limit]

    include_fields = [part.strip() for part in args.include.split(",") if part.strip()]
    if not include_fields:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement list",
            errors=[
                _issue(
                    "list.include.empty",
                    "Include list must contain at least one field.",
                )
            ],
        )

    unknown_fields = [
        field for field in include_fields if field not in LIST_INCLUDE_FIELDS
    ]
    if unknown_fields:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement list",
            errors=[
                _issue(
                    "list.include.invalid",
                    (
                        "Unknown include field(s): "
                        f"{', '.join(sorted(unknown_fields))}. "
                        f"Allowed fields: {', '.join(LIST_INCLUDE_FIELDS)}."
                    ),
                )
            ],
        )

    result_items = [
        {
            "ruid": doc.data["ruid"],
            "rn": doc.rn,
            "rl": doc.rl,
            "rs": doc.rs,
            "scope": doc.data.get("scope"),
            "path": str(doc.file_path),
            "text": doc.data.get("text"),
        }
        for doc in items
    ]

    result_items = [
        {field: item[field] for field in include_fields} for item in result_items
    ]

    return _output(
        as_json=args.as_json,
        ok=True,
        command="requirement list",
        result={
            "count": len(result_items),
            "items": result_items,
        },
    )


def _requirement_inspect(args: argparse.Namespace) -> int:
    docs, issues = _load_requirements(Path(args.requirements))
    if issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement inspect",
            errors=issues,
        )

    by_ruid, by_rn, children_by_rn = _build_indexes(docs)
    target, resolve_issue = _resolve_requirement(args.ruid, by_rn=by_rn)
    if resolve_issue is not None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement inspect",
            errors=[resolve_issue],
        )

    include = set(part.strip() for part in args.include.split(",") if part.strip())
    max_items = args.max_items
    bundle: dict[str, Any] = {
        "requirement": target.data,
        "path": str(target.file_path),
    }

    parent_rn = target.rn[:-1]
    if "parent" in include:
        parent = by_rn.get(parent_rn)
        bundle["parent"] = parent.data if parent else None

    if "siblings" in include:
        siblings = [
            doc.data
            for doc in children_by_rn.get(parent_rn, [])
            if doc.data["ruid"] != target.data["ruid"]
        ]
        bundle["siblings"] = sorted(siblings, key=lambda item: str(item["ruid"]))[
            :max_items
        ]

    if "children" in include:
        children = [doc.data for doc in children_by_rn.get(target.rn, [])]
        bundle["children"] = sorted(children, key=lambda item: str(item["ruid"]))[
            :max_items
        ]

    if "refs" in include:
        refs = target.data.get("refs", {})
        resolved: dict[str, list[dict[str, Any]]] = {}
        for key in REF_KEYS:
            resolved[key] = []
            for ref in refs.get(key, []):
                ref_doc = by_ruid.get(ref)
                if ref_doc is not None:
                    resolved[key].append(ref_doc.data)
        bundle["resolved_refs"] = resolved

    return _output(
        as_json=args.as_json,
        ok=True,
        command="requirement inspect",
        result=bundle,
    )


def _requirement_create(args: argparse.Namespace, *, mode: str) -> int:
    docs, issues = _load_requirements(Path(args.requirements))
    if issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=issues,
        )

    by_ruid, by_rn, _ = _build_indexes(docs)
    anchor, resolve_issue = _resolve_requirement(args.anchor_ruid, by_rn=by_rn)
    if resolve_issue is not None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=[resolve_issue],
        )

    if mode == "create-sibling":
        parent_rn = anchor.rn[:-1]
        if not parent_rn:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement create-sibling",
                errors=[
                    _issue(
                        "hierarchy.root_sibling",
                        "Cannot create sibling for root requirement using create-sibling.",
                    )
                ],
            )
        parent = by_rn.get(parent_rn)
        if parent is None:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement create-sibling",
                errors=[
                    _issue(
                        "hierarchy.parent_missing",
                        f"Sibling parent RN '{parent_rn}' was not found.",
                    )
                ],
            )
    else:
        parent = anchor
        parent_rn = parent.rn

    payload = _make_requirement_payload(args)

    used_rns = set(by_rn)
    new_rn = _next_child_rn(parent_rn, used_rns)
    if new_rn is None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=[
                _rn_exhausted_issue(
                    parent_rn=parent_rn,
                    parent_ruid=str(parent.data["ruid"]),
                )
            ],
        )

    new_ruid = f"{new_rn}{args.rl}{args.rs}"
    payload["ruid"] = new_ruid

    warnings, validation_errors = _validate_proposed_requirement(
        parent=parent,
        child_rl=args.rl,
        child_rs=args.rs,
        child_refs=payload["refs"],
        child_timestamp=str(payload["timestamp"]),
        by_ruid=by_ruid,
        by_rn=by_rn,
    )

    if re.search(r"\bmay\b", str(payload.get("text", "")), re.IGNORECASE):
        warnings.append(
            _issue(
                "text.normative_may",
                "Requirement text uses 'may'; use 'shall' for normative requirements.",
            )
        )

    if validation_errors:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            warnings=warnings,
            errors=validation_errors,
        )

    target_path = Path(args.requirements) / parent_rn / f"{new_ruid}.json"
    would_write = {
        "mode": mode,
        "dry_run": not args.apply,
        "ruid": new_ruid,
        "parent_ruid": parent.data["ruid"],
        "path": str(target_path),
        "requirement": payload,
    }

    if not args.apply:
        return _output(
            as_json=args.as_json,
            ok=True,
            command=f"requirement {mode}",
            warnings=warnings,
            result=would_write,
        )

    _write_requirement_file(target_path, payload)
    return _output(
        as_json=args.as_json,
        ok=True,
        command=f"requirement {mode}",
        warnings=warnings,
        result=would_write,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trussflow",
        description="Trussflow requirements definition tooling.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the Trussflow version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command")
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate requirement files and hierarchy constraints.",
    )
    validate_parser.add_argument(
        "path",
        nargs="?",
        default="requirements",
        help="Path to requirements directory. Defaults to ./requirements.",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    validate_changes_parser = subparsers.add_parser(
        "validate-changes",
        help="Validate errata and amendment files against requirements baseline.",
    )
    validate_changes_parser.add_argument(
        "--requirements",
        default="requirements",
        help="Path to requirements directory. Defaults to ./requirements.",
    )
    validate_changes_parser.add_argument(
        "--errata",
        default="errata",
        help="Path to errata directory. Defaults to ./errata.",
    )
    validate_changes_parser.add_argument(
        "--amendments",
        default="amendments",
        help="Path to amendments directory. Defaults to ./amendments.",
    )
    validate_changes_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    requirement_parser = subparsers.add_parser(
        "requirement",
        help="Read and mechanically author requirements.",
    )
    requirement_subparsers = requirement_parser.add_subparsers(
        dest="requirement_command"
    )

    requirement_get_parser = requirement_subparsers.add_parser(
        "get",
        help="Fetch one requirement by RN or RUID.",
    )
    requirement_get_parser.add_argument(
        "ruid",
        help="Requirement selector (RN or RUID).",
    )
    requirement_get_parser.add_argument(
        "--requirements",
        default="requirements",
        help="Path to requirements directory. Defaults to ./requirements.",
    )
    requirement_get_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    requirement_list_parser = requirement_subparsers.add_parser(
        "list",
        help="List requirements with optional filters.",
    )
    requirement_list_parser.add_argument(
        "--requirements",
        default="requirements",
        help="Path to requirements directory. Defaults to ./requirements.",
    )
    requirement_list_parser.add_argument(
        "--parent", help="Filter to descendants of this parent selector (RN or RUID)."
    )
    requirement_list_parser.add_argument(
        "--rl",
        type=int,
        choices=[0, 1, 2, 3],
        help="Filter by RL decomposition stage.",
    )
    requirement_list_parser.add_argument(
        "--rs",
        choices=["c", "p", "t"],
        help="Filter by RS state.",
    )
    requirement_list_parser.add_argument(
        "--scope",
        choices=["in", "out"],
        help="Filter by scope.",
    )
    requirement_list_parser.add_argument(
        "--text-contains",
        help="Case-insensitive substring filter for requirement text.",
    )
    requirement_list_parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of matching requirements to return.",
    )
    requirement_list_parser.add_argument(
        "--include",
        default=",".join(LIST_INCLUDE_FIELDS),
        help=(
            "Comma-separated fields to include per item. "
            f"Allowed: {', '.join(LIST_INCLUDE_FIELDS)}."
        ),
    )
    requirement_list_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    requirement_inspect_parser = requirement_subparsers.add_parser(
        "inspect",
        help="Fetch one requirement plus nearby context for prompting.",
    )
    requirement_inspect_parser.add_argument(
        "ruid",
        help="Requirement selector (RN or RUID).",
    )
    requirement_inspect_parser.add_argument(
        "--requirements",
        default="requirements",
        help="Path to requirements directory. Defaults to ./requirements.",
    )
    requirement_inspect_parser.add_argument(
        "--include",
        default="parent,siblings,children,refs",
        help="Comma-separated context parts to include.",
    )
    requirement_inspect_parser.add_argument(
        "--max-items",
        type=int,
        default=20,
        help="Maximum siblings/children/refs returned per section.",
    )
    requirement_inspect_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output.",
    )

    def _add_create_arguments(
        parser: argparse.ArgumentParser, *, anchor_help: str
    ) -> None:
        parser.add_argument("anchor_ruid", help=anchor_help)
        parser.add_argument(
            "--requirements",
            default="requirements",
            help="Path to requirements directory. Defaults to ./requirements.",
        )
        parser.add_argument(
            "--rl",
            type=int,
            choices=[0, 1, 2, 3],
            required=True,
            help="RL value for new requirement.",
        )
        parser.add_argument(
            "--rs",
            choices=["c", "p", "t"],
            required=True,
            help="RS value for new requirement.",
        )
        parser.add_argument("--text", required=True, help="Requirement statement text.")
        parser.add_argument(
            "--rationale",
            required=True,
            help="Requirement rationale text.",
        )
        parser.add_argument(
            "--scope",
            choices=["in", "out"],
            required=True,
            help="Requirement scope.",
        )
        parser.add_argument(
            "--depends-on",
            dest="depends_on",
            action="append",
            default=[],
            help="Add a refs.depends_on RUID. Can be repeated.",
        )
        parser.add_argument(
            "--related-to",
            dest="related_to",
            action="append",
            default=[],
            help="Add a refs.related_to RUID. Can be repeated.",
        )
        parser.add_argument(
            "--supersedes",
            dest="supersedes",
            action="append",
            default=[],
            help="Add a refs.supersedes RUID. Can be repeated.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes to disk. Without this flag, command runs as dry-run.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit machine-readable JSON output.",
        )

    def _add_root_create_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--requirements",
            default="requirements",
            help="Path to requirements directory. Defaults to ./requirements.",
        )
        parser.add_argument(
            "--rn",
            required=True,
            help="RN value for root requirement.",
        )
        parser.add_argument(
            "--rl",
            type=int,
            choices=[0, 1, 2, 3],
            required=True,
            help="RL value for root requirement.",
        )
        parser.add_argument(
            "--rs",
            choices=["c", "p", "t"],
            required=True,
            help="RS value for root requirement.",
        )
        parser.add_argument("--text", required=True, help="Requirement statement text.")
        parser.add_argument(
            "--rationale",
            required=True,
            help="Requirement rationale text.",
        )
        parser.add_argument(
            "--scope",
            choices=["in", "out"],
            required=True,
            help="Requirement scope.",
        )
        parser.add_argument(
            "--depends-on",
            dest="depends_on",
            action="append",
            default=[],
            help="Add a refs.depends_on RUID. Can be repeated.",
        )
        parser.add_argument(
            "--related-to",
            dest="related_to",
            action="append",
            default=[],
            help="Add a refs.related_to RUID. Can be repeated.",
        )
        parser.add_argument(
            "--supersedes",
            dest="supersedes",
            action="append",
            default=[],
            help="Add a refs.supersedes RUID. Can be repeated.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes to disk. Without this flag, command runs as dry-run.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit machine-readable JSON output.",
        )

    create_root_parser = requirement_subparsers.add_parser(
        "create-root",
        help="Create the initial root requirement in an empty requirements tree.",
    )
    _add_root_create_arguments(create_root_parser)

    create_child_parser = requirement_subparsers.add_parser(
        "create-child",
        help="Create a child requirement and infer the next available RN.",
    )
    _add_create_arguments(
        create_child_parser,
        anchor_help="Parent requirement selector (RN or RUID).",
    )

    create_sibling_parser = requirement_subparsers.add_parser(
        "create-sibling",
        help="Create a sibling requirement and infer the next available RN.",
    )
    _add_create_arguments(
        create_sibling_parser,
        anchor_help="Existing sibling selector (RN or RUID).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from trussflow import __version__

        print(__version__)
        return 0

    if args.command == "validate":
        issues = validate_requirements_tree(Path(args.path))
        ok = not issues

        if args.as_json:
            payload = {
                "valid": ok,
                "error_count": len(issues),
                "errors": [issue.to_dict() for issue in issues],
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            status = "PASSED" if ok else "FAILED"
            print(f"Validation {status}: {args.path}")
            if not ok:
                for issue in issues:
                    location = issue.file_path
                    if issue.entry_index is not None:
                        location = f"{location}[{issue.entry_index}]"
                    print(f"- {issue.rule} @ {location}: {issue.message}")
                print(f"Total errors: {len(issues)}")
        return 0 if ok else 1

    if args.command == "validate-changes":
        issues = validate_change_artifacts(
            requirements_dir=Path(args.requirements),
            errata_dir=Path(args.errata),
            amendments_dir=Path(args.amendments),
        )
        ok = not issues

        if args.as_json:
            payload = {
                "valid": ok,
                "error_count": len(issues),
                "errors": [issue.to_dict() for issue in issues],
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            status = "PASSED" if ok else "FAILED"
            print(
                "Validation "
                f"{status}: requirements={args.requirements} "
                f"errata={args.errata} amendments={args.amendments}"
            )
            if not ok:
                for issue in issues:
                    location = issue.file_path
                    if issue.entry_index is not None:
                        location = f"{location}[{issue.entry_index}]"
                    print(f"- {issue.rule} @ {location}: {issue.message}")
                print(f"Total errors: {len(issues)}")
        return 0 if ok else 1

    if args.command == "requirement":
        if args.requirement_command == "create-root":
            return _requirement_create_root(args)
        if args.requirement_command == "get":
            return _requirement_get(args)
        if args.requirement_command == "list":
            return _requirement_list(args)
        if args.requirement_command == "inspect":
            return _requirement_inspect(args)
        if args.requirement_command == "create-child":
            return _requirement_create(args, mode="create-child")
        if args.requirement_command == "create-sibling":
            return _requirement_create(args, mode="create-sibling")
        parser.print_help()
        return 0

    parser.print_help()
    return 0
