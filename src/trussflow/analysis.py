"""Gap-analysis reporting built on the GraphStore queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from trussflow.store.graph import GraphStore


@dataclass
class GapReport:
    """Aggregated structural findings about the requirement graph."""

    dangling_requirements: list[dict] = field(default_factory=list)
    dangling_features: list[dict] = field(default_factory=list)
    requirements_without_workpackages: list[dict] = field(default_factory=list)
    autonomy_isolated: list[dict] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return bool(
            self.dangling_requirements
            or self.dangling_features
            or self.requirements_without_workpackages
        )


def run_gap_analysis(store: GraphStore) -> GapReport:
    """Execute the design-doc gap queries and collect the results."""
    return GapReport(
        dangling_requirements=store.dangling_requirements(),
        dangling_features=store.dangling_features(),
        requirements_without_workpackages=store.requirements_without_workpackages(),
        autonomy_isolated=store.autonomy_isolated_requirements(),
    )


def format_report(report: GapReport) -> str:
    """Render a human-readable gap-analysis summary."""
    lines: list[str] = ["Trussflow Gap Analysis", "=" * 22, ""]

    lines.append(
        f"Dangling requirements (no parent): {len(report.dangling_requirements)}"
    )
    for row in report.dangling_requirements:
        lines.append(f"  - {row['id']}: {row['text']}")

    lines.append("")
    lines.append(f"Dangling features (no vision): {len(report.dangling_features)}")
    for row in report.dangling_features:
        lines.append(f"  - {row['id']}: {row['name']}")

    lines.append("")
    lines.append(
        "Approved requirements without work packages: "
        f"{len(report.requirements_without_workpackages)}"
    )
    for row in report.requirements_without_workpackages:
        lines.append(f"  - {row['id']}: {row['text']}")

    lines.append("")
    lines.append(
        f"Autonomy-isolated (Low concern under High parent): "
        f"{len(report.autonomy_isolated)}"
    )
    for row in report.autonomy_isolated:
        lines.append(
            f"  - {row['id']} bound to {row['binding_parent_id']}: {row['text']}"
        )

    return "\n".join(lines)
