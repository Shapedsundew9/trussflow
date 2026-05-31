"""Tests for the pipeline and gap analysis using a fake in-memory store."""

from __future__ import annotations

from trussflow.analysis import format_report, run_gap_analysis
from trussflow.llm.stub import StubProvider
from trussflow.models import RequirementType
from trussflow.pipeline import (
    decompose_features,
    derive_requirements,
    generate_workpackages,
    grade_requirements,
    ingest_vision,
    supersede_requirement,
)

VISION = (
    "The system must persist every requirement for future access. "
    "Security of user data is a top priority. "
    "The application should let founders review proposed solutions."
)


class FakeStore:
    """Minimal GraphStore stand-in recording nodes/edges in memory."""

    def __init__(self):
        self.visions = {}
        self.requirements = {}
        self.features = {}
        self.work_packages = {}
        self.edges = []  # (child, parent) CHILD_OF
        self.implements = []  # (wp_id, req_id)
        self.supersedes = []  # (new_id, old_id)
        self.constraints_called = False

    def ensure_constraints(self):
        self.constraints_called = True

    def upsert_vision(self, vision):
        self.visions[vision.id] = {"id": vision.id, "text": vision.text}

    def upsert_requirement(self, requirement):
        self.requirements[requirement.id] = requirement.to_properties()

    def upsert_feature(self, feature):
        self.features[feature.id] = feature.to_properties()

    def upsert_workpackage(self, work_package):
        self.work_packages[work_package.id] = work_package.to_properties()

    def link_child_of(self, child_id, parent_id):
        self.edges.append((child_id, parent_id))

    def link_implements(self, work_package_id, requirement_id):
        self.implements.append((work_package_id, requirement_id))

    def set_parent(self, child_id, parent_id):
        self.edges = [(c, p) for c, p in self.edges if c != child_id]
        self.edges.append((child_id, parent_id))

    def parent_ids(self, child_id):
        return [p for c, p in self.edges if c == child_id]

    def max_requirement_index(self):
        indices = []
        for rid in self.requirements:
            try:
                indices.append(int(rid.split("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        return max(indices, default=0)

    def supersede_requirement(self, old_id, replacement):
        self.upsert_requirement(replacement)
        if old_id in self.requirements:
            self.requirements[old_id]["status"] = "Superseded"
        self.supersedes.append((replacement.id, old_id))

    def list_requirements(self):
        return list(self.requirements.values())

    def list_visions(self):
        return list(self.visions.values())

    def list_features(self):
        return list(self.features.values())

    def list_workpackages(self):
        return list(self.work_packages.values())

    def set_grade(self, requirement_id, quality_score, is_atomic, is_verifiable):
        self.requirements[requirement_id].update(
            quality_score=quality_score,
            is_atomic=is_atomic,
            is_verifiable=is_verifiable,
        )

    def dangling_requirements(self):
        linked = {c for c, _ in self.edges}
        return [
            {"id": rid, "text": r.get("text", "")}
            for rid, r in self.requirements.items()
            if rid not in linked
        ]

    def dangling_features(self):
        vision_children = {c for c, p in self.edges if p in self.visions}
        return [
            {"id": fid, "name": f.get("name", "")}
            for fid, f in self.features.items()
            if fid not in vision_children
        ]

    def requirements_without_workpackages(self):
        implemented = {req for _, req in self.implements}
        return [
            {"id": rid, "text": r.get("text", "")}
            for rid, r in self.requirements.items()
            if r.get("status") == "Approved" and rid not in implemented
        ]

    def autonomy_isolated_requirements(self):
        return []


def test_ingest_persists_vision_and_requirements(tmp_path):
    doc = tmp_path / "vision.md"
    doc.write_text(VISION, encoding="utf-8")
    store = FakeStore()

    reqs = ingest_vision(str(doc), store, provider=StubProvider())

    assert store.constraints_called
    assert "VIS-001" in store.visions
    assert len(store.requirements) == len(reqs)
    # Every requirement is linked as a child of the vision.
    assert all(parent == "VIS-001" for _, parent in store.edges)
    assert len(store.edges) == len(reqs)


def test_grade_updates_scores(tmp_path):
    doc = tmp_path / "vision.md"
    doc.write_text(VISION, encoding="utf-8")
    store = FakeStore()
    ingest_vision(str(doc), store, provider=StubProvider())

    count = grade_requirements(store, provider=StubProvider())

    assert count == len(store.requirements)
    assert all("quality_score" in r for r in store.requirements.values())


def test_gap_analysis_report_formats(tmp_path):
    doc = tmp_path / "vision.md"
    doc.write_text(VISION, encoding="utf-8")
    store = FakeStore()
    ingest_vision(str(doc), store, provider=StubProvider())

    report = run_gap_analysis(store)
    text = format_report(report)

    # All requirements are children of the vision, so none should be dangling.
    assert report.dangling_requirements == []
    assert "Trussflow Gap Analysis" in text


def _seed(tmp_path) -> FakeStore:
    doc = tmp_path / "vision.md"
    doc.write_text(VISION, encoding="utf-8")
    store = FakeStore()
    ingest_vision(str(doc), store, provider=StubProvider())
    return store


def test_decompose_creates_features_and_reparents(tmp_path):
    store = _seed(tmp_path)
    features = decompose_features(store, provider=StubProvider())

    assert features
    feature_ids = set(store.features)
    # Each feature is a child of the vision.
    assert all((fid, "VIS-001") in store.edges for fid in feature_ids)
    # Every requirement now points at a feature, not the vision.
    for rid in store.requirements:
        parents = store.parent_ids(rid)
        assert parents and all(p in feature_ids for p in parents)


def test_generate_workpackages_links_implements(tmp_path):
    store = _seed(tmp_path)
    count = generate_workpackages(store, provider=StubProvider())

    assert count == len(store.requirements)
    assert len(store.implements) == count
    implemented = {req for _, req in store.implements}
    assert implemented == set(store.requirements)


def test_derive_adds_children_under_parent(tmp_path):
    store = _seed(tmp_path)
    parent_id = next(iter(store.requirements))
    before = set(store.requirements)

    children = derive_requirements(
        store, parent_id, RequirementType.SYSTEM, provider=StubProvider()
    )

    assert children
    new_ids = set(store.requirements) - before
    assert {c.id for c in children} == new_ids
    for child in children:
        assert (child.id, parent_id) in store.edges
        assert child.type is RequirementType.SYSTEM


def test_supersede_marks_old_and_records_trail(tmp_path):
    store = _seed(tmp_path)
    old_id = next(iter(store.requirements))
    old_parents = store.parent_ids(old_id)

    replacement = supersede_requirement(
        store, old_id, "The system shall persist requirements durably.", "CCB change."
    )

    assert store.requirements[old_id]["status"] == "Superseded"
    assert (replacement.id, old_id) in store.supersedes
    # Replacement inherits the old requirement's parents.
    for parent in old_parents:
        assert (replacement.id, parent) in store.edges
