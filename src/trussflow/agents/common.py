"""Shared helpers for agents: schema loading, JSON parsing, ID allocation."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import jsonschema

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = _REPO_ROOT / "schemas"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AgentError(RuntimeError):
    """Raised when an agent produces output that cannot be used."""


@lru_cache(maxsize=8)
def load_schema(name: str) -> dict:
    """Load a JSON Schema from ``schemas/<name>.schema.json``."""
    path = SCHEMAS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise AgentError(f"Schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json(text: str) -> object:
    """Parse JSON from raw model text, tolerating Markdown code fences."""
    candidate = text.strip()
    match = _JSON_FENCE_RE.search(candidate)
    if match:
        candidate = match.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentError(f"Agent did not return valid JSON: {exc}") from exc


def validate(payload: object, schema_name: str) -> None:
    """Validate ``payload`` against a named schema, raising on failure."""
    try:
        jsonschema.validate(payload, load_schema(schema_name))
    except jsonschema.ValidationError as exc:
        raise AgentError(
            f"Agent output failed schema '{schema_name}': {exc.message}"
        ) from exc


def format_requirement_id(index: int) -> str:
    """Format a sequential requirement ID, e.g. ``REQ-101``."""
    return f"REQ-{100 + index}"


def format_feature_id(index: int) -> str:
    """Format a sequential feature ID, e.g. ``FEAT-001``."""
    return f"FEAT-{index:03d}"


def format_workpackage_id(index: int) -> str:
    """Format a sequential work package ID, e.g. ``WP-001``."""
    return f"WP-{index:03d}"
