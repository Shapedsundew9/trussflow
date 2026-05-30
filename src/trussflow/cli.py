"""Command-line interface for Trussflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trussflow.validation import validate_requirements_tree


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

    parser.print_help()
    return 0