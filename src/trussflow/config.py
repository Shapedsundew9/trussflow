"""Runtime configuration and logging for Trussflow.

Configuration is environment-driven so the prototype can run unchanged inside
the dev container, in CI, or against a live Memgraph + Gemini setup. Values are
read once into an immutable :class:`Settings` object.
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


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved from the environment."""

    memgraph_host: str
    memgraph_port: int
    memgraph_user: str
    memgraph_password: str
    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    log_level: str

    @property
    def bolt_uri(self) -> str:
        """Bolt connection URI for the Memgraph driver."""
        return f"bolt://{self.memgraph_host}:{self.memgraph_port}"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


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
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=_env("TRUSSFLOW_GEMINI_MODEL", "gemini-2.5-flash"),
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
