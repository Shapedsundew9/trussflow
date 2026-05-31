"""Runtime configuration and logging for Trussflow.

Configuration is environment-driven so the prototype can run unchanged inside
the dev container, in CI, or against a live Memgraph + Copilot CLI setup. Values
are read once into an immutable :class:`Settings` object.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

try:  # python-dotenv is a hard dependency, but stay import-safe.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - defensive fallback.

    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


_DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"

# Agents whose Copilot CLI model/effort can be overridden individually.
_COPILOT_AGENT_KEYS = (
    "seed_writer",
    "analyst",
    "feature_extractor",
    "work_packager",
    "decomposer",
)


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved from the environment."""

    memgraph_host: str
    memgraph_port: int
    memgraph_user: str
    memgraph_password: str
    llm_provider: str
    copilot_binary: str
    copilot_model: str
    copilot_effort: str
    copilot_allow_all_tools: bool
    copilot_autopilot: bool
    copilot_max_autopilot_continues: int | None
    copilot_timeout: int
    copilot_log_dir: str | None
    copilot_log_level: str | None
    copilot_session_prefix: str
    copilot_agent_overrides: dict[str, dict[str, str]]
    orchestration_enabled: bool
    git_finalize_enabled: bool
    git_push_enabled: bool
    git_remote: str
    git_branch: str | None
    prefect_home: str
    prefect_persist_results: bool
    orchestration_max_repairs: int
    log_level: str

    @property
    def bolt_uri(self) -> str:
        """Bolt connection URI for the Memgraph driver."""
        return f"bolt://{self.memgraph_host}:{self.memgraph_port}"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_opt(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else None


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _copilot_agent_overrides() -> dict[str, dict[str, str]]:
    """Collect per-agent Copilot model/effort overrides from the environment.

    Looks up ``TRUSSFLOW_COPILOT_MODEL_<AGENT>`` and
    ``TRUSSFLOW_COPILOT_EFFORT_<AGENT>`` for each known agent.
    """
    overrides: dict[str, dict[str, str]] = {}
    for agent in _COPILOT_AGENT_KEYS:
        suffix = agent.upper()
        entry: dict[str, str] = {}
        model = _env_opt(f"TRUSSFLOW_COPILOT_MODEL_{suffix}")
        effort = _env_opt(f"TRUSSFLOW_COPILOT_EFFORT_{suffix}")
        if model:
            entry["model"] = model
        if effort:
            entry["effort"] = effort
        if entry:
            overrides[agent] = entry
    return overrides


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings, loading ``.env`` on first access."""
    load_dotenv()
    return Settings(
        memgraph_host=_env("MEMGRAPH_HOST", "localhost"),
        memgraph_port=int(_env("MEMGRAPH_PORT", "7687")),
        memgraph_user=_env("MEMGRAPH_USER", ""),
        memgraph_password=_env("MEMGRAPH_PASSWORD", ""),
        llm_provider=_env("TRUSSFLOW_LLM_PROVIDER", "stub").lower(),
        copilot_binary=_env("TRUSSFLOW_COPILOT_BINARY", "copilot"),
        copilot_model=_env("TRUSSFLOW_COPILOT_MODEL", "gpt-5.4-mini"),
        copilot_effort=_env("TRUSSFLOW_COPILOT_EFFORT", "none"),
        copilot_allow_all_tools=_env_bool("TRUSSFLOW_COPILOT_ALLOW_ALL_TOOLS", True),
        copilot_autopilot=_env_bool("TRUSSFLOW_COPILOT_AUTOPILOT", False),
        copilot_max_autopilot_continues=(
            int(_env("TRUSSFLOW_COPILOT_MAX_AUTOPILOT_CONTINUES", "0")) or None
        ),
        copilot_timeout=int(_env("TRUSSFLOW_COPILOT_TIMEOUT", "600")),
        copilot_log_dir=_env_opt("TRUSSFLOW_COPILOT_LOG_DIR"),
        copilot_log_level=_env_opt("TRUSSFLOW_COPILOT_LOG_LEVEL"),
        copilot_session_prefix=_env("TRUSSFLOW_COPILOT_SESSION_PREFIX", "trussflow"),
        copilot_agent_overrides=_copilot_agent_overrides(),
        orchestration_enabled=_env_bool("TRUSSFLOW_ORCHESTRATION_ENABLED", False),
        git_finalize_enabled=_env_bool("TRUSSFLOW_GIT_FINALIZE_ENABLED", False),
        git_push_enabled=_env_bool("TRUSSFLOW_GIT_PUSH_ENABLED", False),
        git_remote=_env("TRUSSFLOW_GIT_REMOTE", "origin"),
        git_branch=_env_opt("TRUSSFLOW_GIT_BRANCH"),
        prefect_home=_env("TRUSSFLOW_PREFECT_HOME", ".trussflow/prefect"),
        prefect_persist_results=_env_bool("TRUSSFLOW_PREFECT_PERSIST_RESULTS", True),
        orchestration_max_repairs=int(_env("TRUSSFLOW_ORCHESTRATION_MAX_REPAIRS", "2")),
        log_level=_env("TRUSSFLOW_LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once, idempotently.

    Transparency is an explicit project value, so logging is structured and
    timestamped to make every pipeline step observable.
    """
    resolved = (level or get_settings().log_level).upper()
    logging.basicConfig(level=resolved, format=_DEFAULT_LOG_FORMAT)
    logging.getLogger("neo4j").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``trussflow`` hierarchy."""
    return logging.getLogger(f"trussflow.{name}")
