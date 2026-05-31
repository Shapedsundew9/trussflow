"""Domain models mirroring the Memgraph schema in ``docs/design``.

These dataclasses are the in-memory representation of graph nodes. Enum values
are stored verbatim as node properties so the Cypher in the design docs keeps
working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RequirementType(str, Enum):
    """The decomposition layer a requirement belongs to."""

    PRODUCT = "Product"
    SYSTEM = "System"
    DESIGN = "Design"
    IMPLEMENTATION = "Implementation"


class RequirementStatus(str, Enum):
    """Lifecycle state of a requirement."""

    TBD = "TBD"
    TBR = "TBR"
    DEFINED = "Defined"
    APPROVED = "Approved"
    SUPERSEDED = "Superseded"


class UserConcern(str, Enum):
    """How tightly the user wants to govern a requirement.

    ``HIGH`` requirements are human-governed; ``LOW`` requirements may be
    elaborated autonomously by an AI agent within established constraints.
    """

    HIGH = "High"
    LOW = "Low"


class WorkPackageScope(str, Enum):
    """Who is expected to execute a work package."""

    HUMAN = "Human"
    AI_AUTONOMOUS = "AI_Autonomous"


@dataclass
class Vision:
    """Root node: the high-level unstructured goal of the project."""

    id: str
    text: str
    source: str

    def to_properties(self) -> dict[str, str]:
        return {"id": self.id, "text": self.text, "source": self.source}


@dataclass
class Feature:
    """Intermediate capability broken down from the vision."""

    id: str
    name: str
    description: str

    def to_properties(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description}


@dataclass
class Requirement:
    """An atomic, formalized specification statement."""

    id: str
    text: str
    rationale: str
    type: RequirementType
    status: RequirementStatus = RequirementStatus.DEFINED
    user_concern: UserConcern = UserConcern.HIGH
    quality_score: float | None = None
    is_atomic: bool | None = None
    is_verifiable: bool | None = None

    def to_properties(self) -> dict[str, object]:
        props: dict[str, object] = {
            "id": self.id,
            "text": self.text,
            "rationale": self.rationale,
            "type": self.type.value,
            "status": self.status.value,
            "user_concern": self.user_concern.value,
        }
        if self.quality_score is not None:
            props["quality_score"] = self.quality_score
        if self.is_atomic is not None:
            props["is_atomic"] = self.is_atomic
        if self.is_verifiable is not None:
            props["is_verifiable"] = self.is_verifiable
        return props


@dataclass
class WorkPackage:
    """Execution-level task that implements one or more requirements."""

    id: str
    summary: str
    scope: WorkPackageScope = WorkPackageScope.HUMAN

    def to_properties(self) -> dict[str, str]:
        return {"id": self.id, "summary": self.summary, "scope": self.scope.value}


@dataclass
class Finding:
    """A single defect raised by the analyst agent against a requirement."""

    requirement_id: str
    issue: str
    rule: str
    suggested_fix: str
    severity: str = "medium"


@dataclass
class Grade:
    """Aggregated quality assessment for one requirement."""

    requirement_id: str
    quality_score: float
    is_atomic: bool
    is_verifiable: bool
    findings: list[Finding] = field(default_factory=list)
