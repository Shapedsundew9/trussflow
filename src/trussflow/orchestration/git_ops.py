"""Mechanical git finalization for a successful agent step.

On success the orchestration wrapper runs ``git add`` -> ``git commit`` ->
``git push`` (push gated off by default). Each command shells out with a
trusted argv and no shell, mirroring the Copilot CLI provider's subprocess
pattern. Operations are gated by configuration so the offline/test path and CI
never touch a shared remote unless explicitly enabled.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from trussflow.config import Settings, get_logger, get_settings

logger = get_logger("orchestration.git")

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class GitResult:
    """Outcome of the git finalization sequence."""

    performed: bool
    committed: bool
    pushed: bool
    message: str
    commands: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "performed": self.performed,
            "committed": self.committed,
            "pushed": self.pushed,
            "message": self.message,
            "commands": [" ".join(c) for c in self.commands],
        }


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    argv = ["git", *args]
    logger.info("git %s", " ".join(args))
    return subprocess.run(  # noqa: S603 - trusted argv, no shell.
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def finalize(
    paths: list[str],
    message: str,
    *,
    settings: Settings | None = None,
    cwd: Path | None = None,
) -> GitResult:
    """Mechanically stage, commit, and optionally push ``paths``.

    Returns a :class:`GitResult` describing what ran. When finalization is
    disabled the function is a no-op that records why.
    """
    settings = settings or get_settings()
    cwd = cwd or _REPO_ROOT
    commands: list[list[str]] = []

    if not settings.git_finalize_enabled:
        return GitResult(False, False, False, "git finalization disabled", commands)

    if not paths:
        return GitResult(False, False, False, "no paths to commit", commands)

    add_args = ["add", *paths]
    add = _run_git(add_args, cwd=cwd)
    commands.append(["git", *add_args])
    if add.returncode != 0:
        return GitResult(
            True, False, False, f"git add failed: {add.stderr.strip()}", commands
        )

    commit_args = ["commit", "-m", message]
    commit = _run_git(commit_args, cwd=cwd)
    commands.append(["git", *commit_args])
    if commit.returncode != 0:
        # An empty commit (nothing staged) is not a hard failure.
        detail = (commit.stdout or commit.stderr or "").strip()
        return GitResult(True, False, False, f"git commit: {detail}", commands)

    if not settings.git_push_enabled:
        return GitResult(True, True, False, "committed (push disabled)", commands)

    push_args = ["push", settings.git_remote]
    if settings.git_branch:
        push_args.append(settings.git_branch)
    push = _run_git(push_args, cwd=cwd)
    commands.append(["git", *push_args])
    if push.returncode != 0:
        return GitResult(
            True, True, False, f"git push failed: {push.stderr.strip()}", commands
        )

    return GitResult(True, True, True, "committed and pushed", commands)
