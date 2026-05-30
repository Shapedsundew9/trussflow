"""Basic tests for the Trussflow CLI."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def _create_valid_tree(base: Path) -> None:
    requirements = base / "requirements"
    _write(
        requirements / "root.yaml",
        """
- ruid: sA0c
  timestamp: 2026-05-30T12:00:00Z
  text: The product SHALL define a valid root requirement.
  rationale: This is the top-level requirement.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip() + "\n",
    )
    _write(
        requirements / "A" / "sA0c.yaml",
        """
- ruid: sAB1c
  timestamp: 2026-05-30T12:10:00Z
  text: The system SHALL define one valid child requirement.
  rationale: This establishes hierarchy for validation.
  scope: in
  refs:
    depends_on: []
    related_to: []
    supersedes: []
""".strip() + "\n",
    )


def test_cli_version(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out


def test_cli_validate_default_path_success(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["validate"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Validation PASSED" in out


def test_cli_validate_json_failure_for_missing_path(capsys):
    code = main(["validate", "does-not-exist", "--json"])
    out = capsys.readouterr().out

    payload = json.loads(out)
    assert code == 1
    assert payload["valid"] is False
    assert payload["error_count"] >= 1
    first_error = payload["errors"][0]
    assert "error_code" in first_error
    assert first_error["error_code"] == first_error["rule"]
