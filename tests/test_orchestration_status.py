"""Tests for the post-agent status envelope and scripted decision."""

from __future__ import annotations

import pytest

from trussflow.agents.common import AgentError
from trussflow.orchestration.status import (
    AgentStatus,
    Decision,
    decide,
    verify_status,
)


def _status(**kwargs) -> AgentStatus:
    base = {
        "agent": "seed_writer",
        "schema": "requirement_extraction",
        "ok": True,
        "item_count": 1,
        "validated": True,
        "error": None,
    }
    base.update(kwargs)
    return AgentStatus(**base)


def test_verify_status_accepts_wellformed_envelope():
    assert verify_status(_status()) is True


def test_verify_status_rejects_malformed_envelope():
    bad = AgentStatus(
        agent="a", schema="s", ok=True, item_count=-1, validated=True
    )
    with pytest.raises(AgentError):
        verify_status(bad)


def test_decide_continue_on_success():
    assert decide(_status(item_count=3), repairs_remaining=2) is Decision.CONTINUE


def test_decide_repair_when_empty_with_budget():
    status = _status(item_count=0)
    assert decide(status, repairs_remaining=1) is Decision.REPAIR


def test_decide_abort_when_empty_without_budget():
    status = _status(item_count=0)
    assert decide(status, repairs_remaining=0) is Decision.ABORT


def test_decide_abort_when_not_validated():
    status = _status(item_count=0, validated=False, ok=False, error="bad json")
    assert decide(status, repairs_remaining=5) is Decision.ABORT


def test_decide_abort_on_malformed_envelope():
    malformed = AgentStatus(
        agent="a", schema="s", ok=True, item_count=-5, validated=True
    )
    assert decide(malformed, repairs_remaining=5) is Decision.ABORT
