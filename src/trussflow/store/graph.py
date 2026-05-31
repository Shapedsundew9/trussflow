"""Memgraph-backed graph store using the Bolt protocol.

This wraps the ``neo4j`` driver (Bolt-compatible with Memgraph) and exposes the
node/edge operations and gap-analysis queries described in
``docs/design/memgraph-schema.md``. All writes are idempotent upserts so the
pipeline can be re-run safely.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from neo4j import Driver, GraphDatabase

from trussflow.config import Settings, get_logger, get_settings
from trussflow.models import Feature, Requirement, Vision, WorkPackage

logger = get_logger("store.graph")


class GraphStore:
    """Thin, idempotent access layer over Memgraph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._driver: Driver | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def driver(self) -> Driver:
        if self._driver is None:
            auth = None
            if self._settings.memgraph_user:
                auth = (self._settings.memgraph_user, self._settings.memgraph_password)
            logger.info("Connecting to Memgraph at %s", self._settings.bolt_uri)
            self._driver = GraphDatabase.driver(self._settings.bolt_uri, auth=auth)
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextmanager
    def _session(self) -> Iterator[object]:
        with self.driver.session() as session:
            yield session

    def health_check(self) -> bool:
        """Return ``True`` if Memgraph answers a trivial query."""
        try:
            with self._session() as session:
                session.run("RETURN 1 AS ok").single()
            return True
        except Exception as exc:  # pylint: disable=broad-except # pragma: no cover
            logger.error("Memgraph health check failed: %s", exc)
            return False

    # -- schema ------------------------------------------------------------
    def ensure_constraints(self) -> None:
        """Create uniqueness constraints on node IDs (idempotent)."""
        statements = [
            "CREATE CONSTRAINT ON (v:Vision) ASSERT v.id IS UNIQUE",
            "CREATE CONSTRAINT ON (f:Feature) ASSERT f.id IS UNIQUE",
            "CREATE CONSTRAINT ON (r:Requirement) ASSERT r.id IS UNIQUE",
            "CREATE CONSTRAINT ON (w:WorkPackage) ASSERT w.id IS UNIQUE",
        ]
        with self._session() as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                except Exception as exc:  # pylint: disable=broad-except
                    # Constraint may already exist; safe to ignore.
                    logger.debug("Constraint skipped (%s): %s", stmt, exc)

    def reset(self) -> None:
        """Delete every node and relationship. Destructive; prototype only."""
        logger.warning("Resetting graph: deleting all nodes and relationships")
        with self._session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    # -- writes ------------------------------------------------------------
    def upsert_vision(self, vision: Vision) -> None:
        with self._session() as session:
            session.run(
                "MERGE (v:Vision {id: $id}) " "SET v.text = $text, v.source = $source",
                **vision.to_properties(),
            )

    def upsert_requirement(self, requirement: Requirement) -> None:
        with self._session() as session:
            session.run(
                "MERGE (r:Requirement {id: $id}) SET r += $props",
                id=requirement.id,
                props=requirement.to_properties(),
            )

    def link_child_of(self, child_id: str, parent_id: str) -> None:
        """Create ``(child)-[:CHILD_OF]->(parent)`` for any labelled nodes."""
        with self._session() as session:
            session.run(
                "MATCH (c {id: $child}), (p {id: $parent}) "
                "MERGE (c)-[:CHILD_OF]->(p)",
                child=child_id,
                parent=parent_id,
            )

    def set_grade(
        self,
        requirement_id: str,
        quality_score: float,
        is_atomic: bool,
        is_verifiable: bool,
    ) -> None:
        with self._session() as session:
            session.run(
                "MATCH (r:Requirement {id: $id}) "
                "SET r.quality_score = $score, "
                "r.is_atomic = $atomic, r.is_verifiable = $verifiable",
                id=requirement_id,
                score=quality_score,
                atomic=is_atomic,
                verifiable=is_verifiable,
            )

    def upsert_feature(self, feature: Feature) -> None:
        with self._session() as session:
            session.run(
                "MERGE (f:Feature {id: $id}) "
                "SET f.name = $name, f.description = $description",
                **feature.to_properties(),
            )

    def upsert_workpackage(self, work_package: WorkPackage) -> None:
        with self._session() as session:
            session.run(
                "MERGE (w:WorkPackage {id: $id}) "
                "SET w.summary = $summary, w.scope = $scope",
                **work_package.to_properties(),
            )

    def link_implements(self, work_package_id: str, requirement_id: str) -> None:
        """Create ``(wp)-[:IMPLEMENTS]->(requirement)``."""
        with self._session() as session:
            session.run(
                "MATCH (w:WorkPackage {id: $wp}), (r:Requirement {id: $req}) "
                "MERGE (w)-[:IMPLEMENTS]->(r)",
                wp=work_package_id,
                req=requirement_id,
            )

    def link_depends_on(self, requirement_id: str, depends_on_id: str) -> None:
        """Create ``(r)-[:DEPENDS_ON]->(other)``."""
        with self._session() as session:
            session.run(
                "MATCH (r:Requirement {id: $req}), (d:Requirement {id: $dep}) "
                "MERGE (r)-[:DEPENDS_ON]->(d)",
                req=requirement_id,
                dep=depends_on_id,
            )

    def set_parent(self, child_id: str, parent_id: str) -> None:
        """Re-parent a node: replace its outgoing ``CHILD_OF`` edge."""
        with self._session() as session:
            session.run(
                "MATCH (c {id: $child})-[rel:CHILD_OF]->() DELETE rel",
                child=child_id,
            )
            session.run(
                "MATCH (c {id: $child}), (p {id: $parent}) "
                "MERGE (c)-[:CHILD_OF]->(p)",
                child=child_id,
                parent=parent_id,
            )

    def parent_ids(self, child_id: str) -> list[str]:
        """Return the IDs of nodes ``child_id`` is a ``CHILD_OF``."""
        with self._session() as session:
            result = session.run(
                "MATCH ({id: $child})-[:CHILD_OF]->(p) RETURN p.id AS id",
                child=child_id,
            )
            return [str(record["id"]) for record in result]

    def supersede_requirement(self, old_id: str, replacement: Requirement) -> None:
        """Replace ``old_id`` with ``replacement``, recording the change trail.

        The old requirement is marked ``Superseded`` and a
        ``(new)-[:SUPERSEDES]->(old)`` edge preserves the historical trail.
        """
        self.upsert_requirement(replacement)
        with self._session() as session:
            session.run(
                "MATCH (old:Requirement {id: $old}) " "SET old.status = 'Superseded'",
                old=old_id,
            )
            session.run(
                "MATCH (new:Requirement {id: $new}), (old:Requirement {id: $old}) "
                "MERGE (new)-[:SUPERSEDES]->(old)",
                new=replacement.id,
                old=old_id,
            )

    # -- reads / analysis --------------------------------------------------
    def list_requirements(self) -> list[dict]:
        with self._session() as session:
            result = session.run("MATCH (r:Requirement) RETURN r ORDER BY r.id")
            return [dict(record["r"]) for record in result]

    def list_visions(self) -> list[dict]:
        with self._session() as session:
            result = session.run("MATCH (v:Vision) RETURN v ORDER BY v.id")
            return [dict(record["v"]) for record in result]

    def list_features(self) -> list[dict]:
        with self._session() as session:
            result = session.run("MATCH (f:Feature) RETURN f ORDER BY f.id")
            return [dict(record["f"]) for record in result]

    def list_workpackages(self) -> list[dict]:
        with self._session() as session:
            result = session.run("MATCH (w:WorkPackage) RETURN w ORDER BY w.id")
            return [dict(record["w"]) for record in result]

    def max_requirement_index(self) -> int:
        """Return the highest numeric suffix among ``REQ-<n>`` IDs (0 if none)."""
        with self._session() as session:
            result = session.run(
                "MATCH (r:Requirement) WHERE r.id STARTS WITH 'REQ-' "
                "RETURN r.id AS id"
            )
            indices = []
            for record in result:
                try:
                    indices.append(int(str(record["id"]).split("-", 1)[1]))
                except (ValueError, IndexError):
                    continue
            return max(indices, default=0)

    def dangling_requirements(self) -> list[dict]:
        """Requirements that do not trace up to any parent (scope creep)."""
        with self._session() as session:
            result = session.run(
                "MATCH (r:Requirement) "
                "WHERE NOT (r)-[:CHILD_OF]->() "
                "RETURN r.id AS id, r.text AS text ORDER BY r.id"
            )
            return [dict(record) for record in result]

    def requirements_without_workpackages(self) -> list[dict]:
        """Approved requirements lacking any implementation task."""
        with self._session() as session:
            result = session.run(
                "MATCH (r:Requirement) "
                "WHERE r.status = 'Approved' "
                "AND NOT (:WorkPackage)-[:IMPLEMENTS]->(r) "
                "RETURN r.id AS id, r.text AS text ORDER BY r.id"
            )
            return [dict(record) for record in result]

    def autonomy_isolated_requirements(self) -> list[dict]:
        """Low-concern requirements bound to a high-concern ancestor."""
        with self._session() as session:
            result = session.run(
                "MATCH (r:Requirement {user_concern: 'Low'})"
                "-[:CHILD_OF*1..3]->(parent:Requirement {user_concern: 'High'}) "
                "RETURN r.id AS id, r.text AS text, "
                "parent.id AS binding_parent_id ORDER BY r.id"
            )
            return [dict(record) for record in result]

    def dangling_features(self) -> list[dict]:
        """Features that do not trace up to any vision (scope creep)."""
        with self._session() as session:
            result = session.run(
                "MATCH (f:Feature) "
                "WHERE NOT (f)-[:CHILD_OF]->(:Vision) "
                "RETURN f.id AS id, f.name AS name ORDER BY f.id"
            )
            return [dict(record) for record in result]

    def impact_analysis(self, requirement_id: str) -> list[dict]:
        """Return every node downstream of ``requirement_id``.

        Traverses ``DEPENDS_ON`` and ``CHILD_OF`` edges inbound to the changed
        requirement, giving the set of design layers affected by a change.
        """
        with self._session() as session:
            result = session.run(
                "MATCH (root:Requirement {id: $id})"
                "<-[:DEPENDS_ON|CHILD_OF*1..]-(dependent) "
                "RETURN DISTINCT dependent.id AS id, dependent.text AS text, "
                "dependent.status AS status ORDER BY dependent.id",
                id=requirement_id,
            )
            return [dict(record) for record in result]
