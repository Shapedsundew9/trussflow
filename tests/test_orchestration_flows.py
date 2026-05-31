"""Tests for the Prefect orchestration flow.

A private temporary ``PREFECT_HOME`` is configured *before* importing the flow
module so the real run-history database under ``.trussflow/`` is never touched.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# Point Prefect at a throwaway home before importing the flow module.
_PREFECT_HOME = tempfile.mkdtemp(prefix="trussflow-prefect-test-")
os.environ["PREFECT_HOME"] = _PREFECT_HOME

from trussflow.config import get_settings  # noqa: E402
from trussflow.llm.stub import StubProvider  # noqa: E402
from trussflow.orchestration.flows import run_agent_step  # noqa: E402
from trussflow.orchestration.runner import OrchestrationAbort, StepResult  # noqa: E402
from trussflow.orchestration.status import AgentStatus, Decision  # noqa: E402
from trussflow.pipeline import ingest_vision  # noqa: E402

from tests.test_pipeline import VISION, FakeStore  # noqa: E402


def _ok_status(agent: str, count: int) -> AgentStatus:
    return AgentStatus(
        agent=agent, schema="requirement_extraction", ok=True,
        item_count=count, validated=True,
    )


def test_run_agent_step_continue_on_success():
    def dispatch(_ctx):
        return StepResult(value=[1, 2], status=_ok_status("analyst", 2), artifacts=[])

    outcome = run_agent_step("analyst", {}, dispatch)

    assert outcome.decision is Decision.CONTINUE
    assert outcome.result.value == [1, 2]
    # Finalization is disabled by default, so git is a no-op.
    assert outcome.git.performed is False


def test_run_agent_step_aborts_on_failed_check(tmp_path):
    missing = tmp_path / "nope.md"

    def dispatch(_ctx):  # pragma: no cover - must never run.
        raise AssertionError("dispatch should not run when a check fails")

    with pytest.raises(OrchestrationAbort):
        run_agent_step("seed_writer", {"source_path": str(missing)}, dispatch)


def test_run_agent_step_repairs_then_continues():
    calls = {"n": 0}

    def dispatch(_ctx):
        calls["n"] += 1
        count = 0 if calls["n"] == 1 else 1
        return StepResult(
            value=["x"] * count, status=_ok_status("analyst", count), artifacts=[]
        )

    outcome = run_agent_step("analyst", {}, dispatch)

    assert calls["n"] == 2  # empty first, redispatched, then non-empty.
    assert outcome.decision is Decision.CONTINUE


def test_pipeline_step_runs_through_orchestration(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUSSFLOW_ORCHESTRATION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        doc = tmp_path / "vision.md"
        doc.write_text(VISION, encoding="utf-8")
        store = FakeStore()

        reqs = ingest_vision(str(doc), store, provider=StubProvider())

        assert reqs
        assert len(store.requirements) == len(reqs)
        assert store.constraints_called
    finally:
        get_settings.cache_clear()
