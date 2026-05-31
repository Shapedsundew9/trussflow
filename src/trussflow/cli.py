"""Command-line interface for Trussflow.

Subcommands:
  ingest <path>   Extract requirements from a vision document into the graph.
  grade           Grade every requirement in the graph for quality.
  decompose       Extract features and group requirements beneath them.
  workpackages    Generate work packages implementing each requirement.
  derive <id>     Derive lower-level child requirements from a requirement.
  supersede <id>  Replace a requirement, recording the change trail.
  impact <id>     Show every node affected by changing a requirement.
  analyze         Run structural gap analysis and print a report.
  list            List requirements currently stored in the graph.
  features        List stored features.
  reset           Delete all nodes and relationships (destructive).
  health          Check connectivity to Memgraph.
"""

from __future__ import annotations

import argparse
import sys

from trussflow.analysis import format_report, run_gap_analysis
from trussflow.config import configure_logging, get_logger
from trussflow.models import RequirementType
from trussflow.pipeline import (
    decompose_features,
    derive_requirements,
    generate_workpackages,
    grade_requirements,
    ingest_vision,
    supersede_requirement,
)
from trussflow.store.graph import GraphStore

logger = get_logger("cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trussflow", description=__doc__)
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a vision document.")
    p_ingest.add_argument("path", help="Path to the vision document.")
    p_ingest.add_argument(
        "--vision-id", default="VIS-001", help="ID for the vision node."
    )

    sub.add_parser("grade", help="Grade all requirements.")
    sub.add_parser("decompose", help="Extract features and group requirements.")
    sub.add_parser("workpackages", help="Generate work packages for requirements.")

    p_derive = sub.add_parser("derive", help="Derive child requirements.")
    p_derive.add_argument("requirement_id", help="Parent requirement ID.")
    p_derive.add_argument(
        "--type",
        dest="target_type",
        default="System",
        choices=[t.value for t in RequirementType],
        help="Decomposition layer for the derived children.",
    )

    p_supersede = sub.add_parser("supersede", help="Supersede a requirement.")
    p_supersede.add_argument("requirement_id", help="Requirement ID to supersede.")
    p_supersede.add_argument("--text", required=True, help="Replacement statement.")
    p_supersede.add_argument(
        "--rationale",
        default="Superseded by change control.",
        help="Rationale for the replacement.",
    )

    p_impact = sub.add_parser("impact", help="Show downstream impact of a change.")
    p_impact.add_argument("requirement_id", help="Requirement ID to analyze.")

    sub.add_parser("analyze", help="Run gap analysis and print a report.")
    sub.add_parser("list", help="List stored requirements.")
    sub.add_parser("features", help="List stored features.")
    sub.add_parser("reset", help="Delete all graph data (destructive).")
    sub.add_parser("health", help="Check Memgraph connectivity.")
    return parser


def _cmd_ingest(args: argparse.Namespace, store: GraphStore) -> int:
    requirements = ingest_vision(args.path, store, vision_id=args.vision_id)
    print(f"Ingested {len(requirements)} requirement(s):")
    for req in requirements:
        print(f"  {req.id} [{req.type.value}/{req.user_concern.value}] {req.text}")
    return 0


def _cmd_grade(_args: argparse.Namespace, store: GraphStore) -> int:
    count = grade_requirements(store)
    print(f"Graded {count} requirement(s).")
    return 0


def _cmd_decompose(_args: argparse.Namespace, store: GraphStore) -> int:
    features = decompose_features(store)
    print(f"Created {len(features)} feature(s):")
    for feature in features:
        print(f"  {feature.id} {feature.name}")
    return 0


def _cmd_workpackages(_args: argparse.Namespace, store: GraphStore) -> int:
    count = generate_workpackages(store)
    print(f"Generated {count} work package(s).")
    return 0


def _cmd_derive(args: argparse.Namespace, store: GraphStore) -> int:
    children = derive_requirements(
        store, args.requirement_id, RequirementType(args.target_type)
    )
    print(f"Derived {len(children)} child requirement(s) from {args.requirement_id}:")
    for child in children:
        print(f"  {child.id} [{child.type.value}] {child.text}")
    return 0


def _cmd_supersede(args: argparse.Namespace, store: GraphStore) -> int:
    replacement = supersede_requirement(
        store, args.requirement_id, args.text, args.rationale
    )
    print(f"{args.requirement_id} superseded by {replacement.id}.")
    return 0


def _cmd_impact(args: argparse.Namespace, store: GraphStore) -> int:
    rows = store.impact_analysis(args.requirement_id)
    if not rows:
        print(f"No downstream nodes depend on {args.requirement_id}.")
        return 0
    print(f"{len(rows)} node(s) affected by changing {args.requirement_id}:")
    for row in rows:
        print(f"  {row['id']} [{row.get('status', '?')}] {row.get('text', '')}")
    return 0


def _cmd_features(_args: argparse.Namespace, store: GraphStore) -> int:
    rows = store.list_features()
    if not rows:
        print("No features stored.")
        return 0
    for row in rows:
        print(f"  {row['id']} {row.get('name', '')}")
    return 0


def _cmd_analyze(_args: argparse.Namespace, store: GraphStore) -> int:
    report = run_gap_analysis(store)
    print(format_report(report))
    return 0


def _cmd_list(_args: argparse.Namespace, store: GraphStore) -> int:
    rows = store.list_requirements()
    if not rows:
        print("No requirements stored.")
        return 0
    for row in rows:
        score = row.get("quality_score")
        score_str = f" score={score}" if score is not None else ""
        print(
            f"  {row['id']} [{row.get('type', '?')}]{score_str} {row.get('text', '')}"
        )
    return 0


def _cmd_reset(_args: argparse.Namespace, store: GraphStore) -> int:
    store.reset()
    print("Graph reset.")
    return 0


def _cmd_health(_args: argparse.Namespace, store: GraphStore) -> int:
    ok = store.health_check()
    print("Memgraph: OK" if ok else "Memgraph: UNREACHABLE")
    return 0 if ok else 1


_DISPATCH = {
    "ingest": _cmd_ingest,
    "grade": _cmd_grade,
    "decompose": _cmd_decompose,
    "workpackages": _cmd_workpackages,
    "derive": _cmd_derive,
    "supersede": _cmd_supersede,
    "impact": _cmd_impact,
    "analyze": _cmd_analyze,
    "list": _cmd_list,
    "features": _cmd_features,
    "reset": _cmd_reset,
    "health": _cmd_health,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(args.log_level)

    handler = _DISPATCH[args.command]
    try:
        with GraphStore() as store:
            return handler(args, store)
    except Exception as exc:  # pylint: disable=broad-except
        # Surface a single clean error at the CLI boundary.
        logger.error("Command '%s' failed: %s", args.command, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
