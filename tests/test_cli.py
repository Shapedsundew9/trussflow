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
        requirements / "root.json",
        json.dumps(
            {
                "ruid": "A0c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define a valid root requirement.",
                "rationale": "This is the top-level requirement.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(
        requirements / "A" / "AB1c.json",
        json.dumps(
            {
                "ruid": "AB1c",
                "timestamp": "2026-05-30T12:10:00Z",
                "text": "The system shall define one valid child requirement.",
                "rationale": "This establishes hierarchy for validation.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _create_valid_change_artifacts(base: Path) -> None:
    _write(
        base / "errata" / "batch-001.json",
        json.dumps(
            [
                {
                    "errata_id": "ERR-A-20260530T120000Z",
                    "discovered_timestamp": "2026-05-30T12:00:00Z",
                    "analyst_id": "agent.requirement-analyst",
                    "error_type": "gap",
                    "description": "A measurable child requirement is missing.",
                    "affected_ruids": ["A0c"],
                    "violated_rule": "text.verifiability",
                    "root_cause": "Current text is not measurable.",
                    "solutions": [
                        {
                            "solution_id": "primary",
                            "action_type": "create_requirement",
                            "description": "Create measurable child requirement.",
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _write(
        base / "amendments" / "batch-001.json",
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-A-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                            "parent_ruid": "A0c",
                            "new_ruid": "AC1p",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Supports verifiability.",
                                "scope": "in",
                                "refs": {
                                    "depends_on": [],
                                    "related_to": [],
                                    "supersedes": [],
                                },
                            },
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
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


def test_cli_validate_changes_success(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    _create_valid_change_artifacts(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["validate-changes"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Validation PASSED" in out


def test_cli_validate_changes_json_failure_for_missing_errata(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    _create_valid_change_artifacts(tmp_path)
    monkeypatch.chdir(tmp_path)

    (tmp_path / "errata" / "batch-001.json").unlink()

    code = main(["validate-changes", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 1
    assert payload["valid"] is False
    assert payload["error_count"] >= 1
    assert any(err["error_code"] == "artifact.empty" for err in payload["errors"])
