"""End-to-end orchestration of the requirements pipeline.

Plain Python for the prototype (Prefect comes later). Each agent run persists a
raw input/output artifact under ``artifacts/`` so every step is auditable,
matching the project's transparency goal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from trussflow.agents.analyst import AnalystAgent
from trussflow.agents.common import format_requirement_id
from trussflow.agents.decomposer import DecomposerAgent
from trussflow.agents.feature_extractor import FeatureExtractorAgent
from trussflow.agents.seed_writer import SeedWriterAgent
from trussflow.agents.work_packager import WorkPackagerAgent
from trussflow.config import get_logger
from trussflow.llm.base import LLMProvider
from trussflow.llm.factory import get_provider
from trussflow.models import (
    Feature,
    Requirement,
    RequirementStatus,
    RequirementType,
    UserConcern,
    Vision,
)
from trussflow.store.graph import GraphStore

logger = get_logger("pipeline")

_REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = _REPO_ROOT / "artifacts"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_artifact(kind: str, data: object) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{_timestamp()}-{kind}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote artifact %s", path)
    return path


def ingest_vision(
    source_path: str,
    store: GraphStore,
    provider: LLMProvider | None = None,
    vision_id: str = "VIS-001",
) -> list[Requirement]:
    """Read a vision document, extract requirements, and persist the graph."""
    provider = provider or get_provider()
    text = Path(source_path).read_text(encoding="utf-8")
    vision = Vision(id=vision_id, text=text, source=source_path)

    agent = SeedWriterAgent(provider)
    requirements = agent.run(source_path, text)

    store.ensure_constraints()
    store.upsert_vision(vision)
    for requirement in requirements:
        store.upsert_requirement(requirement)
        store.link_child_of(requirement.id, vision.id)

    _write_artifact(
        "ingest",
        {
            "source": source_path,
            "vision_id": vision_id,
            "provider": provider.name,
            "requirements": [r.to_properties() for r in requirements],
        },
    )
    logger.info("Ingested %d requirement(s) from %s", len(requirements), source_path)
    return requirements


def grade_requirements(
    store: GraphStore,
    provider: LLMProvider | None = None,
) -> int:
    """Grade every requirement in the graph and persist the scores."""
    provider = provider or get_provider()
    rows = store.list_requirements()
    requirements = [
        Requirement(
            id=row["id"],
            text=row.get("text", ""),
            rationale=row.get("rationale", ""),
            type=_safe_enum(row.get("type")),
        )
        for row in rows
    ]
    if not requirements:
        logger.warning("No requirements to grade")
        return 0

    agent = AnalystAgent(provider)
    grades = agent.run(requirements)
    for grade in grades:
        store.set_grade(
            grade.requirement_id,
            grade.quality_score,
            grade.is_atomic,
            grade.is_verifiable,
        )

    _write_artifact(
        "grade",
        {
            "provider": provider.name,
            "grades": [
                {
                    "id": g.requirement_id,
                    "quality_score": g.quality_score,
                    "is_atomic": g.is_atomic,
                    "is_verifiable": g.is_verifiable,
                    "findings": [vars(f) for f in g.findings],
                }
                for g in grades
            ],
        },
    )
    logger.info("Graded %d requirement(s)", len(grades))
    return len(grades)


def _row_to_requirement(row: dict) -> Requirement:
    """Reconstruct a Requirement model from a stored graph row."""
    return Requirement(
        id=row["id"],
        text=row.get("text", ""),
        rationale=row.get("rationale", ""),
        type=_safe_enum(row.get("type")),
        status=_safe_status(row.get("status")),
        user_concern=_safe_concern(row.get("user_concern")),
    )


def decompose_features(
    store: GraphStore,
    provider: LLMProvider | None = None,
) -> list[Feature]:
    """Extract features from the vision and group requirements beneath them.

    Creates ``(Feature)-[:CHILD_OF]->(Vision)`` and re-parents each top-level
    requirement under its best-matching feature.
    """
    provider = provider or get_provider()
    vision_rows = store.list_visions()
    if not vision_rows:
        logger.warning("No vision present; run 'ingest' first")
        return []
    vision = vision_rows[0]

    features = FeatureExtractorAgent(provider).run(vision.get("text", ""))
    if not features:
        return []

    store.ensure_constraints()
    for feature in features:
        store.upsert_feature(feature)
        store.link_child_of(feature.id, vision["id"])

    requirements = [_row_to_requirement(r) for r in store.list_requirements()]
    for requirement in requirements:
        feature = _best_feature(requirement, features)
        store.set_parent(requirement.id, feature.id)

    _write_artifact(
        "decompose",
        {
            "provider": provider.name,
            "vision_id": vision["id"],
            "features": [f.to_properties() for f in features],
            "assignments": {r.id: _best_feature(r, features).id for r in requirements},
        },
    )
    logger.info("Created %d feature(s) and grouped requirements", len(features))
    return features


def generate_workpackages(
    store: GraphStore,
    provider: LLMProvider | None = None,
) -> int:
    """Generate one work package per requirement and link IMPLEMENTS edges."""
    provider = provider or get_provider()
    requirements = [_row_to_requirement(r) for r in store.list_requirements()]
    if not requirements:
        logger.warning("No requirements to plan work packages for")
        return 0

    pairs = WorkPackagerAgent(provider).run(requirements)
    store.ensure_constraints()
    for work_package, requirement_id in pairs:
        store.upsert_workpackage(work_package)
        store.link_implements(work_package.id, requirement_id)

    _write_artifact(
        "workpackages",
        {
            "provider": provider.name,
            "work_packages": [
                {
                    "id": wp.id,
                    "summary": wp.summary,
                    "scope": wp.scope.value,
                    "implements": req_id,
                }
                for wp, req_id in pairs
            ],
        },
    )
    logger.info("Generated %d work package(s)", len(pairs))
    return len(pairs)


def derive_requirements(
    store: GraphStore,
    parent_id: str,
    target_type: RequirementType,
    provider: LLMProvider | None = None,
) -> list[Requirement]:
    """Derive child requirements from a parent and link them via CHILD_OF."""
    provider = provider or get_provider()
    rows = {r["id"]: r for r in store.list_requirements()}
    if parent_id not in rows:
        raise ValueError(f"Unknown requirement: {parent_id}")
    parent = _row_to_requirement(rows[parent_id])

    start_index = store.max_requirement_index() + 1 - 100
    children = DecomposerAgent(provider).run(parent, target_type, start_index)

    store.ensure_constraints()
    for child in children:
        store.upsert_requirement(child)
        store.link_child_of(child.id, parent.id)

    _write_artifact(
        "derive",
        {
            "provider": provider.name,
            "parent_id": parent_id,
            "target_type": target_type.value,
            "children": [c.to_properties() for c in children],
        },
    )
    logger.info("Derived %d child requirement(s) from %s", len(children), parent_id)
    return children


def supersede_requirement(
    store: GraphStore,
    old_id: str,
    new_text: str,
    rationale: str,
) -> Requirement:
    """Supersede a requirement with a new one, preserving the change trail."""
    rows = {r["id"]: r for r in store.list_requirements()}
    if old_id not in rows:
        raise ValueError(f"Unknown requirement: {old_id}")
    old = _row_to_requirement(rows[old_id])

    new_index = store.max_requirement_index() + 1 - 100
    replacement = Requirement(
        id=format_requirement_id(new_index),
        text=new_text,
        rationale=rationale,
        type=old.type,
        status=RequirementStatus.DEFINED,
        user_concern=old.user_concern,
    )

    store.supersede_requirement(old_id, replacement)
    # Preserve the old requirement's place in the hierarchy.
    for parent_id in store.parent_ids(old_id):
        store.link_child_of(replacement.id, parent_id)

    _write_artifact(
        "supersede",
        {
            "old_id": old_id,
            "replacement": replacement.to_properties(),
        },
    )
    logger.info("Superseded %s with %s", old_id, replacement.id)
    return replacement


def _best_feature(requirement: Requirement, features: list[Feature]) -> Feature:
    """Pick the feature whose name best overlaps the requirement text."""
    req_tokens = set(_tokenize(requirement.text))
    best = features[0]
    best_score = -1
    for feature in features:
        score = len(req_tokens & set(_tokenize(feature.name)))
        if score > best_score:
            best_score = score
            best = feature
    return best


def _tokenize(text: str) -> list[str]:
    return [
        t
        for t in "".join(c.lower() if c.isalnum() else " " for c in text).split()
        if len(t) > 3
    ]


def _safe_enum(value: object):
    try:
        return RequirementType(value)
    except (ValueError, TypeError):
        return RequirementType.PRODUCT


def _safe_status(value: object):
    try:
        return RequirementStatus(value)
    except (ValueError, TypeError):
        return RequirementStatus.DEFINED


def _safe_concern(value: object):
    try:
        return UserConcern(value)
    except (ValueError, TypeError):
        return UserConcern.HIGH
