"""GitHub Copilot CLI LLM provider.

Drives the ``copilot`` command-line tool programmatically. A single named
session is shared across every agent invocation in a pipeline run: the first
completion creates the session with ``--name`` and subsequent completions resume
it with ``--resume`` so context is preserved. Each provider instance may carry
agent-specific ``model``/``effort`` overrides while sharing one session.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from trussflow.config import Settings, get_logger, get_settings
from trussflow.llm.base import LLMResponse

logger = get_logger("llm.copilot")

_JSON_INSTRUCTION = (
    "\n\nRespond with a single valid JSON document only. "
    "Do not include explanations or Markdown code fences."
)


@dataclass
class CopilotSession:
    """Run-scoped Copilot CLI session.

    Holds the session name shared across agent calls. ``started`` flips to True
    after the first successful completion so later calls resume instead of
    creating a new session.
    """

    name: str
    started: bool = False


class CopilotProvider:
    """LLM provider backed by the GitHub Copilot CLI."""

    name = "copilot"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session: CopilotSession | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session = session
        self._model = model or self._settings.copilot_model
        self._effort = effort or self._settings.copilot_effort

    def _build_argv(self, prompt: str) -> list[str]:
        settings = self._settings
        argv: list[str] = [settings.copilot_binary, "-p", prompt, "-s", "--no-color"]

        if settings.copilot_allow_all_tools:
            argv.append("--allow-all-tools")
        if self._model:
            argv += ["--model", self._model]
        if self._effort:
            argv += ["--effort", self._effort]

        if self._session is not None:
            if self._session.started:
                argv += ["--resume", self._session.name]
            else:
                argv += ["--name", self._session.name]

        if settings.copilot_autopilot:
            argv.append("--autopilot")
            if settings.copilot_max_autopilot_continues is not None:
                argv += [
                    "--max-autopilot-continues",
                    str(settings.copilot_max_autopilot_continues),
                ]

        if settings.copilot_log_dir:
            argv += ["--log-dir", settings.copilot_log_dir]
        if settings.copilot_log_level:
            argv += ["--log-level", settings.copilot_log_level]

        return argv

    def complete(self, prompt: str, *, json_mode: bool = False) -> LLMResponse:
        if json_mode:
            prompt = prompt + _JSON_INSTRUCTION

        argv = self._build_argv(prompt)
        resuming = bool(self._session and self._session.started)
        logger.info(
            "Invoking copilot CLI (model=%s, effort=%s, %s)",
            self._model,
            self._effort,
            "resume" if resuming else "new session",
        )

        try:
            result = subprocess.run(  # noqa: S603 - trusted argv, no shell.
                argv,
                capture_output=True,
                text=True,
                timeout=self._settings.copilot_timeout,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover - environment issue.
            raise RuntimeError(
                f"copilot CLI not found ({self._settings.copilot_binary!r}). "
                "Install it or set TRUSSFLOW_COPILOT_BINARY."
            ) from exc
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing.
            raise RuntimeError(
                f"copilot CLI timed out after {self._settings.copilot_timeout}s."
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"copilot CLI failed (exit {result.returncode}): "
                f"{(result.stderr or '').strip()}"
            )

        if self._session is not None:
            self._session.started = True

        return LLMResponse(
            text=(result.stdout or "").strip(),
            provider=self.name,
            raw=result,
        )
