"""Tests for the Copilot CLI provider and its session management."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from trussflow.config import get_settings
from trussflow.llm.copilot import CopilotProvider, CopilotSession


def _settings():
    # Use a fresh, non-cached Settings clone so test env tweaks don't leak.
    get_settings.cache_clear()
    return get_settings()


def _fake_run(captured: list[list[str]], *, returncode: int = 0, stdout: str = "{}"):
    def runner(argv, **_kwargs):
        captured.append(list(argv))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return runner


def test_complete_builds_expected_argv(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured, stdout='{"ok": true}'))

    provider = CopilotProvider(_settings(), model="claude", effort="high")
    response = provider.complete("hello", json_mode=True)

    assert response.provider == "copilot"
    assert response.text == '{"ok": true}'

    argv = captured[0]
    assert argv[0] == "copilot"
    assert "-p" in argv
    # Prompt carries the JSON-only instruction in json_mode.
    prompt = argv[argv.index("-p") + 1]
    assert prompt.startswith("hello")
    assert "JSON" in prompt
    assert "-s" in argv
    assert "--allow-all-tools" in argv
    assert argv[argv.index("--model") + 1] == "claude"
    assert argv[argv.index("--effort") + 1] == "high"


def test_session_creates_then_resumes(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))

    session = CopilotSession(name="trussflow-run1")
    provider = CopilotProvider(_settings(), session=session)

    provider.complete("first")
    provider.complete("second")

    first, second = captured
    assert "--name" in first and first[first.index("--name") + 1] == "trussflow-run1"
    assert "--resume" not in first
    assert "--resume" in second and second[second.index("--resume") + 1] == "trussflow-run1"
    assert "--name" not in second
    assert session.started is True


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run([], returncode=2, stdout=""),
    )
    provider = CopilotProvider(_settings())
    with pytest.raises(RuntimeError, match="copilot CLI failed"):
        provider.complete("boom")


def test_autopilot_flags(monkeypatch):
    monkeypatch.setenv("TRUSSFLOW_COPILOT_AUTOPILOT", "true")
    monkeypatch.setenv("TRUSSFLOW_COPILOT_MAX_AUTOPILOT_CONTINUES", "5")
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))

    provider = CopilotProvider(_settings())
    provider.complete("go")

    argv = captured[0]
    assert "--autopilot" in argv
    assert argv[argv.index("--max-autopilot-continues") + 1] == "5"
    get_settings.cache_clear()
