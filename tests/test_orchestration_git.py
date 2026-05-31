"""Tests for the mechanical git finalization sequence."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from trussflow.config import get_settings
from trussflow.orchestration import git_ops


def _settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()
    return settings


def _fake_run(captured, *, returncode=0, stdout="", stderr=""):
    def runner(argv, **_kwargs):
        captured.append(list(argv))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return runner


def test_finalize_disabled_is_noop(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))
    settings = _settings(monkeypatch, TRUSSFLOW_GIT_FINALIZE_ENABLED="false")

    result = git_ops.finalize(["artifacts/x.json"], "msg", settings=settings)

    assert result.performed is False
    assert captured == []


def test_finalize_commits_without_push(monkeypatch, tmp_path):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))
    settings = _settings(
        monkeypatch,
        TRUSSFLOW_GIT_FINALIZE_ENABLED="true",
        TRUSSFLOW_GIT_PUSH_ENABLED="false",
    )

    result = git_ops.finalize(
        ["artifacts/x.json"], "trussflow(seed_writer)", settings=settings, cwd=tmp_path
    )

    assert result.committed is True
    assert result.pushed is False
    assert captured[0][:2] == ["git", "add"]
    assert captured[1][:2] == ["git", "commit"]
    assert all(cmd[1] != "push" for cmd in captured)


def test_finalize_pushes_when_enabled(monkeypatch, tmp_path):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))
    settings = _settings(
        monkeypatch,
        TRUSSFLOW_GIT_FINALIZE_ENABLED="true",
        TRUSSFLOW_GIT_PUSH_ENABLED="true",
        TRUSSFLOW_GIT_REMOTE="origin",
        TRUSSFLOW_GIT_BRANCH="main",
    )

    result = git_ops.finalize(["a.json"], "msg", settings=settings, cwd=tmp_path)

    assert result.pushed is True
    push = captured[-1]
    assert push[1] == "push"
    assert push[2] == "origin"
    assert push[3] == "main"


def test_finalize_empty_commit_not_hard_failure(monkeypatch, tmp_path):
    captured: list[list[str]] = []

    def runner(argv, **_kwargs):
        captured.append(list(argv))
        if argv[1] == "commit":
            return SimpleNamespace(
                returncode=1, stdout="nothing to commit", stderr=""
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", runner)
    settings = _settings(monkeypatch, TRUSSFLOW_GIT_FINALIZE_ENABLED="true")

    result = git_ops.finalize(["a.json"], "msg", settings=settings, cwd=tmp_path)

    assert result.performed is True
    assert result.committed is False
    assert "nothing to commit" in result.message
