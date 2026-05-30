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

RUID_TOKEN_RE = re.compile(r"^[0-9A-Z]+$")
RUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
REF_KEYS = ("depends_on", "related_to", "supersedes")
LIST_INCLUDE_FIELDS = (
    "ruid",
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
    rl: int
    rs: str


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
        if not RUID_TOKEN_RE.match(ruid):
            issues.append(
                _issue("ruid.parse", f"Unable to parse RUID '{ruid}'.", str(file_path))
            )
            continue

        rl = entry.get("rl")
        rs = entry.get("rs")
        if not isinstance(rl, int) or rl not in (0, 1, 2, 3):
            issues.append(
                _issue(
                    "rl.parse",
                    f"Requirement '{ruid}' is missing a valid integer rl in [0,1,2,3].",
                    str(file_path),
                )
            )
            continue
        if not isinstance(rs, str) or rs not in ("c", "p", "t"):
            issues.append(
                _issue(
                    "rs.parse",
                    f"Requirement '{ruid}' is missing a valid rs in ['c','p','t'].",
                    str(file_path),
                )
            )
            continue

        docs.append(RequirementDoc(data=entry, file_path=file_path, rl=rl, rs=rs))

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
    dict[str, list[RequirementDoc]],
]:
    by_ruid: dict[str, RequirementDoc] = {}
    children_by_ruid: dict[str, list[RequirementDoc]] = {}

    for doc in docs:
        ruid = str(doc.data["ruid"])
        by_ruid[ruid] = doc

    for doc in docs:
        parent_ruid = str(doc.data["ruid"])[:-1]
        children_by_ruid.setdefault(parent_ruid, []).append(doc)

    return by_ruid, children_by_ruid


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


def _next_child_ruid(parent_ruid: str, used_ruids: set[str]) -> str | None:
    for ch in RUID_CHARS:
        candidate = f"{parent_ruid}{ch}"
        if candidate not in used_ruids:
            return candidate
    return None


def _ruid_exhausted_issue(*, parent_ruid: str) -> ValidationIssue:
    return _issue(
        "ruid.exhausted",
        (
            f"No available one-character RUID extension under parent RUID '{parent_ruid}'. "
            f"Maximum immediate children is {len(RUID_CHARS)}."
        ),
    )


def _resolve_ruid_selector(
    selector: str,
    *,
    by_ruid: dict[str, RequirementDoc] | None = None,
) -> str | None:
    _ = by_ruid
    if RUID_TOKEN_RE.match(selector):
        return selector
    return None


def _resolve_requirement(
    selector: str,
    *,
    by_ruid: dict[str, RequirementDoc],
) -> tuple[RequirementDoc | None, ValidationIssue | None]:
    ruid = _resolve_ruid_selector(selector, by_ruid=by_ruid)
    if ruid is None:
        return None, _issue(
            "ruid.parse",
            f"Identifier must be a valid RUID token: '{selector}'.",
        )

    target = by_ruid.get(ruid)
    if target is None:
        return None, _issue(
            "requirement.not_found",
            f"Requirement not found for RUID '{ruid}'.",
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


def _collect_raw_refs(
    args: argparse.Namespace,
) -> tuple[dict[str, list[str]], list[ValidationIssue]]:
    refs: dict[str, list[str]] = {
        "depends_on": list(args.depends_on or []),
        "related_to": list(args.related_to or []),
        "supersedes": list(args.supersedes or []),
    }
    issues: list[ValidationIssue] = []

    for item in list(getattr(args, "refs", []) or []):
        key: str | None = None
        value: str | None = None
        if ":" in item:
            key, value = item.split(":", 1)
        elif "=" in item:
            key, value = item.split("=", 1)

        key = (key or "").strip()
        value = (value or "").strip()

        if key not in REF_KEYS or not value:
            issues.append(
                _issue(
                    "refs.arg",
                    (
                        "Ref must be '<type>:<selector>' or '<type>=<selector>' "
                        "with type in depends_on, related_to, supersedes."
                    ),
                )
            )
            continue

        refs[key].append(value)

    return refs, issues


def _resolve_ref_selectors(
    raw_refs: dict[str, list[str]],
    *,
    by_ruid: dict[str, RequirementDoc],
) -> tuple[dict[str, list[str]], list[ValidationIssue]]:
    resolved: dict[str, list[str]] = {key: [] for key in REF_KEYS}
    issues: list[ValidationIssue] = []

    for key in REF_KEYS:
        for selector in raw_refs.get(key, []):
            ruid = _resolve_ruid_selector(selector, by_ruid=by_ruid)
            if ruid is None:
                issues.append(
                    _issue(
                        "refs.parse",
                        f"Reference '{selector}' in refs.{key} must be a RUID.",
                    )
                )
                continue

            target = by_ruid.get(ruid)
            if target is None:
                issues.append(
                    _issue(
                        "refs.exists",
                        f"Reference '{selector}' in refs.{key} does not exist.",
                    )
                )
                continue

            if ruid not in resolved[key]:
                resolved[key].append(ruid)

    return resolved, issues


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
        ancestor_ruid = str(parent.data["ruid"])[:-1]
        while not has_eligible_ancestor and ancestor_ruid:
            ancestor = by_ruid.get(ancestor_ruid)
            if ancestor and ancestor.rl in (0, 1, 2):
                has_eligible_ancestor = True
                break
            ancestor_ruid = ancestor_ruid[:-1]

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
                            f"New requirement must be newer than superseded requirement RUID {superseded_ruid}."
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

    payload = _make_requirement_payload(args)
    raw_refs, ref_arg_issues = _collect_raw_refs(args)
    payload["refs"] = raw_refs

    if ref_arg_issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement create-root",
            errors=ref_arg_issues,
        )
    next_root_ruid = _next_child_ruid("", set())
    if next_root_ruid is None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command="requirement create-root",
            errors=[
                _issue(
                    "ruid.exhausted",
                    "No available root RUID values remain.",
                )
            ],
        )

    payload["ruid"] = next_root_ruid
    payload["rl"] = 0
    payload["rs"] = "p"

    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []

    resolved_refs, ref_issues = _resolve_ref_selectors(payload["refs"], by_ruid={})
    payload["refs"] = resolved_refs
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

    by_ruid, _ = _build_indexes(docs)
    target, resolve_issue = _resolve_requirement(args.ruid, by_ruid=by_ruid)
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

    by_ruid, _ = _build_indexes(docs)
    items = docs
    if args.parent:
        parent_ruid = _resolve_ruid_selector(args.parent, by_ruid=by_ruid)
        if parent_ruid is None:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement list",
                errors=[
                    _issue(
                        "ruid.parse",
                        f"Parent selector must be a RUID: '{args.parent}'.",
                    )
                ],
            )
        items = [
            doc
            for doc in items
            if str(doc.data["ruid"]).startswith(parent_ruid)
            and str(doc.data["ruid"]) != parent_ruid
        ]
    if args.scope is not None:
        items = [doc for doc in items if doc.data.get("scope") == args.scope]
    if args.text_contains:
        needle = args.text_contains.lower()
        items = [
            doc for doc in items if needle in str(doc.data.get("text", "")).lower()
        ]
    if args.root_only:
        items = [doc for doc in items if doc.file_path.name == "root.json"]

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

    by_ruid, children_by_ruid = _build_indexes(docs)
    target, resolve_issue = _resolve_requirement(args.ruid, by_ruid=by_ruid)
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

    target_ruid = str(target.data["ruid"])
    parent_ruid = target_ruid[:-1]
    if "parent" in include:
        parent = by_ruid.get(parent_ruid)
        bundle["parent"] = parent.data if parent else None

    if "siblings" in include:
        siblings = [
            doc.data
            for doc in children_by_ruid.get(parent_ruid, [])
            if doc.data["ruid"] != target.data["ruid"]
        ]
        bundle["siblings"] = sorted(siblings, key=lambda item: str(item["ruid"]))[
            :max_items
        ]

    if "children" in include:
        children = [doc.data for doc in children_by_ruid.get(target_ruid, [])]
        bundle["children"] = sorted(children, key=lambda item: str(item["ruid"]))[
            :max_items
        ]

    if "refs" in include:
        refs = target.data.get("refs", {})
        resolved: dict[str, list[dict[str, Any]]] = {}
        for key in REF_KEYS:
            resolved[key] = []
            for ref in refs.get(key, []):
                ref_ruid = _resolve_ruid_selector(ref, by_ruid=by_ruid)
                ref_doc = by_ruid.get(ref_ruid) if ref_ruid is not None else None
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

    by_ruid, _ = _build_indexes(docs)
    anchor, resolve_issue = _resolve_requirement(args.anchor_ruid, by_ruid=by_ruid)
    if resolve_issue is not None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=[resolve_issue],
        )

    if mode == "create-sibling":
        parent_ruid = str(anchor.data["ruid"])[:-1]
        if not parent_ruid:
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
        parent = by_ruid.get(parent_ruid)
        if parent is None:
            return _output(
                as_json=args.as_json,
                ok=False,
                command="requirement create-sibling",
                errors=[
                    _issue(
                        "hierarchy.parent_missing",
                        f"Sibling parent RUID '{parent_ruid}' was not found.",
                    )
                ],
            )
    else:
        parent = anchor
        parent_ruid = str(parent.data["ruid"])

    payload = _make_requirement_payload(args)
    raw_refs, ref_arg_issues = _collect_raw_refs(args)
    if ref_arg_issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=ref_arg_issues,
        )
    resolved_refs, ref_issues = _resolve_ref_selectors(raw_refs, by_ruid=by_ruid)
    payload["refs"] = resolved_refs
    if ref_issues:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=ref_issues,
        )

    used_ruids = set(by_ruid)
    new_ruid = _next_child_ruid(parent_ruid, used_ruids)
    if new_ruid is None:
        return _output(
            as_json=args.as_json,
            ok=False,
            command=f"requirement {mode}",
            errors=[_ruid_exhausted_issue(parent_ruid=str(parent.data["ruid"]))],
        )

    payload["ruid"] = new_ruid
    payload["rl"] = parent.rl
    payload["rs"] = "p"

    warnings, validation_errors = _validate_proposed_requirement(
        parent=parent,
        child_rl=payload["rl"],
        child_rs=payload["rs"],
        child_refs=payload["refs"],
        child_timestamp=str(payload["timestamp"]),
        by_ruid=by_ruid,
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

    target_path = Path(args.requirements) / parent_ruid / f"{new_ruid}.json"
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
        help="Fetch one requirement by RUID.",
    )
    requirement_get_parser.add_argument(
        "ruid",
        help="Requirement selector (RUID).",
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
        "--parent", help="Filter to descendants of this parent selector (RUID)."
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
        "--root-only",
        action="store_true",
        help="Return only requirements loaded from files named root.json.",
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
        help="Requirement selector (RUID).",
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
            help="Add a refs.depends_on selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--related-to",
            dest="related_to",
            action="append",
            default=[],
            help="Add a refs.related_to selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--supersedes",
            dest="supersedes",
            action="append",
            default=[],
            help="Add a refs.supersedes selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--ref",
            dest="refs",
            action="append",
            default=[],
            help=(
                "Add a ref as '<type>:<selector>' or '<type>=<selector>' where type "
                "is depends_on, related_to, or supersedes. Can be repeated."
            ),
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
            help="Add a refs.depends_on selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--related-to",
            dest="related_to",
            action="append",
            default=[],
            help="Add a refs.related_to selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--supersedes",
            dest="supersedes",
            action="append",
            default=[],
            help="Add a refs.supersedes selector (RUID). Can be repeated.",
        )
        parser.add_argument(
            "--ref",
            dest="refs",
            action="append",
            default=[],
            help=(
                "Add a ref as '<type>:<selector>' or '<type>=<selector>' where type "
                "is depends_on, related_to, or supersedes. Can be repeated."
            ),
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
        help=(
            "Create the initial root requirement in an empty requirements tree; "
            "RUID is auto-assigned from 0-9 then A-Z (first root RUID is 0)."
        ),
    )
    _add_root_create_arguments(create_root_parser)

    create_child_parser = requirement_subparsers.add_parser(
        "create-child",
        help=(
            "Create a child requirement; RUID is inferred as the first unused "
            "one-character extension in 0-9 then A-Z order."
        ),
    )
    _add_create_arguments(
        create_child_parser,
        anchor_help="Parent requirement selector (RUID).",
    )

    create_sibling_parser = requirement_subparsers.add_parser(
        "create-sibling",
        help=(
            "Create a sibling requirement; RUID is inferred under the parent as the "
            "first unused one-character extension in 0-9 then A-Z order."
        ),
    )
    _add_create_arguments(
        create_sibling_parser,
        anchor_help="Existing sibling selector (RUID).",
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
